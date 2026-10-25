"""Independent raw-label audit. Never edits annotations or assumes image order."""
import csv
import json
import ast
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .camera_screen_geometry import load_calibration, intersect_gaze
from .io import sha256, write_json, write_jsonl


def boundary_status(xy, size, pixel_centers=False):
    xy, size = np.asarray(xy, float), np.asarray(size, float)
    if xy.shape != (2,) or size.shape != (2,) or not np.isfinite(np.r_[xy,size]).all() or (size <= 1).any():
        raise ValueError("Invalid coordinate or display size")
    upper = size-1 if pixel_centers else size
    # Positive margin means inside; negative means outside. Each edge is explicit.
    margins = np.array([xy[0], upper[0]-xy[0], xy[1], upper[1]-xy[1]])
    outside_axes = [axis for axis, x, hi in zip(["x","y"],xy,upper) if x < 0 or x > hi]
    delta = xy-np.clip(xy,0,upper)
    return {"on_screen": not outside_axes, "outside_axes": outside_axes,
            "signed_edge_margins_px": dict(zip(["left","right","top","bottom"],margins.tolist())),
            "signed_axis_excess_px": delta.tolist(),
            "signed_nearest_margin_px": float(margins.min()),
            "nearest_boundary_distance_px": float(np.linalg.norm(delta)) if outside_axes else float(margins.min()),
            "on_exact_boundary": bool(not outside_axes and ((xy==0).any() or (xy==upper).any()))}


def raw_annotations(root):
    base = Path(root)/"raw/mpiifacegaze"
    rows,invalid=[],[]
    for file in sorted(base.rglob("p[0-9][0-9].txt")):
        subject=file.stem; cal=load_calibration(file.parent/"Calibration",subject)
        for line_no,line in enumerate(file.read_text().splitlines(),1):
            if not line.strip(): continue
            t=line.split()
            try:
                if len(t)!=28 or t[-1] not in ("left","right"): raise ValueError("28 columns/eye flag")
                a=np.array(t[1:27],float)
                if not np.isfinite(a).all(): raise ValueError("nonfinite")
                relative=Path(t[0])
                if relative.is_absolute() or '..' in relative.parts: raise ValueError("invalid image ID")
                rows.append({"id":str(file.parent.relative_to(base)/relative),"subject_id":subject,
                             "day":relative.parts[0],"image_id":relative.name,"annotation_line":line_no,
                             "gaze_screen_px":a[:2].tolist(),"screen_size_px":[cal['screen']['width_pixel'],cal['screen']['height_pixel']],
                             "landmarks_2d":a[2:14].reshape(6,2).tolist(),"head_rvec":a[14:17].tolist(),
                             "head_translation_mm":a[17:20].tolist(),"face_center_mm":a[20:23].tolist(),
                             "gaze_target_mm":a[23:26].tolist(),"eye_subset":t[-1],"calibration":cal,
                             "image_path":str((file.parent/relative).resolve())})
            except (ValueError,IndexError) as e:invalid.append({"file":str(file),"line":line_no,"reason":str(e)})
    if not rows:raise ValueError("No local raw MPII annotation files")
    if len({r['id'] for r in rows})!=len(rows):raise ValueError("Duplicate raw annotation IDs")
    return rows,invalid


def view_ids(rows):
    bad_days={(r['subject_id'],r['day']) for r in rows if not boundary_status(r['gaze_screen_px'],r['screen_size_px'])['on_screen']}
    return {'Original':[r['id'] for r in rows],
            'On-screen':[r['id'] for r in rows if boundary_status(r['gaze_screen_px'],r['screen_size_px'])['on_screen']],
            'Day-filtered':[r['id'] for r in rows if (r['subject_id'],r['day']) not in bad_days]}


def audit_outliers(root='data',output='reports/mpii_audit'):
    root,output=Path(root),Path(output)
    rows,invalid=raw_annotations(root)
    outliers=[];days=defaultdict(list);subjects={};centers_only=[];boundaries=[];predicate_ids=[]
    for row in rows:
        xy,size=row['gaze_screen_px'],row['screen_size_px']
        closed=boundary_status(xy,size);centers=boundary_status(xy,size,True)
        days[(row['subject_id'],row['day'])].append((row,closed))
        if closed['on_exact_boundary']:boundaries.append(row['id'])
        if closed['on_screen'] and not centers['on_screen']:centers_only.append(row['id'])
        # Faithful numeric predicate from pperle source, including astype(int).
        x,y=np.asarray(xy).astype(int);w,h=size
        if not (0<=x<=w and 0<=y<=h):predicate_ids.append(row['id'])
        if closed['on_screen']:continue
        direction=np.asarray(row['gaze_target_mm'])-row['face_center_mm']
        try:
            ray=intersect_gaze(row['face_center_mm'],direction,row['calibration'])
            error=float(np.linalg.norm(np.asarray(ray['screen_xy_px'])-xy))
            consistent=error<.01
        except ValueError as e:consistent=False;error=None
        source=row['calibration']['source_files']['monitorPose.mat']
        outliers.append({**{k:row[k] for k in ['id','subject_id','day','image_id','screen_size_px','gaze_screen_px','gaze_target_mm']},
                         **closed,'monitor_pose_calibration_id':source['sha256'],
                         'image_locally_available':Path(row['image_path']).is_file(),
                         'geometry_reconstruction_consistent':consistent,'geometry_error_px':error,
                         'cause':'unresolved','boundary_convention':'continuous closed [0,W] x [0,H]'})
    views=view_ids(rows)
    write_json(output/'views.json',{'schema':'immutable-label-id-views-v1','views':views,
                                  'boundary':'closed continuous [0,W] x [0,H]; centers reported separately',
                                  'source_annotations_sha256':{str(p.relative_to(root)):sha256(p) for p in sorted((root/'raw/mpiifacegaze').rglob('p[0-9][0-9].txt'))}})
    day_table=[]
    for (subject,day),values in sorted(days.items()):
        count=sum(not s['on_screen'] for r,s in values)
        coordinates=np.array([r['gaze_screen_px'] for r,_ in values])
        day_table.append({'subject_id':subject,'day':day,'n':len(values),'outside':count,'outside_fraction':count/len(values),
                          'screen_width_px':values[0][0]['screen_size_px'][0],'screen_height_px':values[0][0]['screen_size_px'][1],
                          'x_min':float(coordinates[:,0].min()),'x_max':float(coordinates[:,0].max()),
                          'y_min':float(coordinates[:,1].min()),'y_max':float(coordinates[:,1].max()),
                          'max_excess_px':max(max(0,-s['signed_nearest_margin_px']) for r,s in values)})
    output.mkdir(parents=True,exist_ok=True)
    with (output/'outliers_by_day.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(day_table[0]));writer.writeheader();writer.writerows(day_table)
    for subject in sorted({r['subject_id'] for r in rows}):
        total=sum(r['subject_id']==subject for r in rows);bad=[r for r in outliers if r['subject_id']==subject]
        subjects[subject]={'n':total,'outside':len(bad),'outside_fraction':len(bad)/total,
                           'bad_days':[d for d in day_table if d['subject_id']==subject and d['outside']]}
    ours={r['id'] for r in outliers};reference=set(predicate_ids)
    published_path=output/'reference/published_mpiifacegaze_not_on_screen.csv'
    published=None
    if published_path.exists():
        with published_path.open() as f:published_rows=list(csv.DictReader(f))
        published_ids={'Data/'+r['file_name'] for r in published_rows}
        by_id={r['id']:r for r in rows}
        mismatched=[]
        for r in published_rows:
            key='Data/'+r['file_name']
            if key in by_id and (not np.array_equal(ast.literal_eval(r['on_screen_gaze_position']),by_id[key]['gaze_screen_px']) or not np.array_equal(ast.literal_eval(r['monitor_pixels']),by_id[key]['screen_size_px'])):mismatched.append(key)
        published={'n':len(published_rows),'same_ids':published_ids==ours,
                   'ours_only':sorted(ours-published_ids),'published_only':sorted(published_ids-ours),
                   'coordinate_or_size_mismatch_ids':mismatched,'sha256':sha256(published_path),
                   'source_url':'https://drive.google.com/uc?export=download&id=1Cq25df9124q8vkdsJO1BiqjuLSWlXz1r',
                   'source_readme_commit':'6e4e2a5ca355680721798556fa671e8266de5705'}
    literal=output/'reference/literal_current360/not_on_screen.csv'
    literal_ids=[]
    if literal.exists():
        with literal.open() as f:literal_ids=['Data/'+r['file_name'] for r in csv.DictReader(f)]
    positional_mismatches=0
    for s in subjects:
        group=[r for r in rows if r['subject_id']==s]
        local=sorted(r['id'] for r in group if Path(r['image_path']).is_file())
        positional_mismatches+=sum(actual!=expected['id'] for actual,expected in zip(local,group))
    summary={'n_valid_format':len(rows),'invalid':invalid,'subjects':subjects,'outside_n':len(outliers),
             'boundary_closed_ids':boundaries,'on_closed_but_outside_pixel_centers_ids':centers_only,
             'pixel_center_outside_n':len(outliers)+len(centers_only),
             'axis_counts':dict(Counter('+'.join(r['outside_axes']) for r in outliers)),
             'excess_sign_counts':{'has_left_or_top_excess':sum(any(x<0 for x in r['signed_axis_excess_px']) for r in outliers),
                                   'has_right_or_bottom_excess':sum(any(x>0 for x in r['signed_axis_excess_px']) for r in outliers)},
             'outlier_coordinate_extents':{s:{'x_min':min(r['gaze_screen_px'][0] for r in outliers if r['subject_id']==s),
                                               'x_max':max(r['gaze_screen_px'][0] for r in outliers if r['subject_id']==s),
                                               'y_min':min(r['gaze_screen_px'][1] for r in outliers if r['subject_id']==s),
                                               'y_max':max(r['gaze_screen_px'][1] for r in outliers if r['subject_id']==s)} for s in sorted({r['subject_id'] for r in outliers})},
             'view_sizes':{k:len(v) for k,v in views.items()},
             'pperle':{'source_commit':json.loads((output/'reference/revision.json').read_text()) if (output/'reference/revision.json').exists() else None,
                       'numeric_predicate_n':len(reference),'same_numeric_predicate_ids':reference==ours,
                       'published_csv':published,
                       'ours_only':sorted(ours-reference),'reference_predicate_only':sorted(reference-ours),
                       'literal_sparse_directory_ids':literal_ids,'literal_false_ids':sorted(set(literal_ids)-ours),
                       'positional_id_mismatches_on_sparse_tree':positional_mismatches,
                       'readme_rates_percent':{'p02':.043,'p07':8.79,'p10':.39},
                       'note':'Script assumes every annotation row corresponds to next sorted image. Predicate comparison on all labels is not a claim to execute original full-image dataset.'},
             'hypotheses':{'screen_configuration_change':'unresolved: one participant-level calibration, no dated screen config log',
                           'label_generation_error':'unresolved: 2D/3D consistency can share same calibration error',
                           'one_pixel_boundary_convention':'testable separately; boundary-only ID list is explicit',
                           'fractional_integer_truncation':'original coordinates checked; predicate agreement recorded'},
             'local_images_for_outliers':sum(r['image_locally_available'] for r in outliers)}
    write_jsonl(output/'outliers.jsonl',outliers)
    write_json(output/'audit_summary.json',summary)
    boundary_ids=set(boundaries)|set(centers_only)
    write_jsonl(output/'boundary_samples.jsonl',[{'id':r['id'],'xy':r['gaze_screen_px'],'size':r['screen_size_px']} for r in rows if r['id'] in boundary_ids])
    from .visualize_mpii import pyplot
    plt=pyplot();figures=output/'figures';figures.mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,3,figsize=(15,4),constrained_layout=True)
    for ax,subject in zip(axes,['p02','p07','p10']):
        group=[r for r in rows if r['subject_id']==subject]
        if not group:
            ax.set_title(subject+' (not present)');continue
        points=np.asarray([r['gaze_screen_px'] for r in group])/group[0]['screen_size_px']
        inside=np.array([boundary_status(r['gaze_screen_px'],r['screen_size_px'])['on_screen'] for r in group])
        ax.scatter(*points[inside].T,s=3,alpha=.25);ax.scatter(*points[~inside].T,s=8,c='red',label='outside')
        ax.plot([0,1,1,0,0],[0,0,1,1,0],c='black');ax.invert_yaxis();ax.set_title(subject);ax.legend();ax.set_xlabel('x/W');ax.set_ylabel('y/H')
    fig.savefig(figures/'coordinates.png',dpi=140);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,4),constrained_layout=True)
    axes[0].hist([r['nearest_boundary_distance_px'] for r in outliers],bins=30);axes[0].set_xlabel('nearest display boundary distance [px]');axes[0].set_ylabel('outside labels')
    bad=[d for d in day_table if d['outside']]
    axes[1].bar([d['subject_id']+'/'+d['day'] for d in bad],[d['outside_fraction'] for d in bad]);axes[1].tick_params(axis='x',rotation=90,labelsize=7);axes[1].set_ylabel('out-of-bounds fraction on day')
    fig.savefig(figures/'boundary_and_days.png',dpi=150);plt.close(fig)
    all_subjects=sorted(subjects);all_days=sorted({d['day'] for d in day_table})
    matrix=np.full((len(all_subjects),len(all_days)),np.nan)
    for d in day_table:matrix[all_subjects.index(d['subject_id']),all_days.index(d['day'])]=d['outside_fraction']
    fig,ax=plt.subplots(figsize=(16,5),constrained_layout=True)
    im=ax.imshow(matrix,aspect='auto',vmin=0,cmap='magma')
    ax.set_yticks(range(len(all_subjects)),all_subjects)
    ax.set_xticks(range(len(all_days)),all_days,rotation=90,fontsize=6)
    ax.set_xlabel('Session/day ID; blank means absent (not zero)');fig.colorbar(im,ax=ax,label='outside fraction')
    fig.savefig(figures/'all_subject_days.png',dpi=150);plt.close(fig)
    lines=['# MPIIFaceGaze out-of-bounds audit','',f"Independent raw parsing: {len(rows)} valid rows; {len(outliers)} outside continuous display; {len(centers_only)} additional outside pixel-center extent; {len(boundaries)} exactly on continuous boundaries.",'',
           '| Subject | N | Outside | Rate % | Bad days |','|---|---:|---:|---:|---|']
    for s,v in subjects.items():lines.append(f"| {s} | {v['n']} | {v['outside']} | {100*v['outside_fraction']:.4f} | "+', '.join(d['day']+':'+str(d['outside']) for d in v['bad_days'])+' |')
    lines+=['','## External source comparison','',
            '[pperle source](https://github.com/pperle/gaze-tracking/blob/main/dataset/mpii_face_gaze_errors.py) uses integer truncation and closed `[0,W] x [0,H]`. On all local labels, the ID predicate agrees: '+str(reference==ours)+'.',
            'Published CSV linked from the pinned README: '+(f"{published['n']} rows; identical ID set={published['same_ids']}; coordinate/size mismatches={len(published['coordinate_or_size_mismatch_ids'])}. Source URL and SHA256 are recorded in audit_summary.json." if published else 'not locally available; no claim of comparing its actual IDs.'),
            f"The original script on this sparse photo tree outputs {len(literal_ids)} IDs; positional alignment mismatches {positional_mismatches} images. Its numeric predicate must be distinguished from its file/row alignment assumption.",
            'External README percentages (p02 .043%, p07 8.79%, p10 .39%) do not numerically equal these local FaceGaze annotation percentages. Same affected participants; denominator/version/source of percentage differences unresolved. Its calibrated 2–3 degree results use user-specific gaze calibration and are not zero-shot LOSO comparisons.',
            '', '## Evidence and unresolved causes','',
            f"The {len(outliers)} outliers occupy {len(bad)} subject/day pairs. Concentration is observed, but day number is a session identifier, not a calendar date. Screen-configuration changes and label-generation mistakes remain unresolved without independent dated device logs or the affected photos.",
            'The ray reconstruction checks shared 2D/3D calibration consistency only. It cannot establish that either label matches physical fixation. Boundary-only cases are kept separate and never silently deleted.','',
            'Distance convention: signed edge margins are positive inside; signed axis excess is negative left/top and positive right/bottom; nearest boundary distance is Euclidean distance to the rectangle for outside points.','',
            'Views are ID manifests only. Original images, calibration and labels remain untouched.']
    (output/'outlier_summary.md').write_text('\n'.join(lines)+'\n')
    return summary
