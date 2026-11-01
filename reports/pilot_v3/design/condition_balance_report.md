# Condition balance

16组，每组24个独立目标；每cell6项，每zone6项；各cell×zone计数为1或2。每个target跨16组覆盖4条件×4区域。全Session目标保留为reserved，不出现在其他页干扰项。seed=42。

{
  "groups": 16,
  "trials_per_session": 24,
  "unique_targets_per_session": {
    "0": 24,
    "1": 24,
    "2": 24,
    "3": 24,
    "4": 24,
    "5": 24,
    "6": 24,
    "7": 24,
    "8": 24,
    "9": 24,
    "10": 24,
    "11": 24,
    "12": 24,
    "13": 24,
    "14": 24,
    "15": 24
  },
  "cell_counts": {
    "0": {
      "easy_low": 6,
      "hard_low": 6,
      "hard_high": 6,
      "easy_high": 6
    },
    "1": {
      "hard_low": 6,
      "easy_high": 6,
      "easy_low": 6,
      "hard_high": 6
    },
    "2": {
      "easy_high": 6,
      "hard_high": 6,
      "hard_low": 6,
      "easy_low": 6
    },
    "3": {
      "hard_high": 6,
      "easy_low": 6,
      "easy_high": 6,
      "hard_low": 6
    },
    "4": {
      "easy_low": 6,
      "hard_low": 6,
      "hard_high": 6,
      "easy_high": 6
    },
    "5": {
      "hard_low": 6,
      "easy_high": 6,
      "easy_low": 6,
      "hard_high": 6
    },
    "6": {
      "easy_high": 6,
      "hard_high": 6,
      "hard_low": 6,
      "easy_low": 6
    },
    "7": {
      "hard_high": 6,
      "easy_low": 6,
      "easy_high": 6,
      "hard_low": 6
    },
    "8": {
      "easy_low": 6,
      "hard_low": 6,
      "hard_high": 6,
      "easy_high": 6
    },
    "9": {
      "hard_low": 6,
      "easy_high": 6,
      "easy_low": 6,
      "hard_high": 6
    },
    "10": {
      "easy_high": 6,
      "hard_high": 6,
      "hard_low": 6,
      "easy_low": 6
    },
    "11": {
      "hard_high": 6,
      "easy_low": 6,
      "easy_high": 6,
      "hard_low": 6
    },
    "12": {
      "easy_low": 6,
      "hard_low": 6,
      "hard_high": 6,
      "easy_high": 6
    },
    "13": {
      "hard_low": 6,
      "easy_high": 6,
      "easy_low": 6,
      "hard_high": 6
    },
    "14": {
      "easy_high": 6,
      "hard_high": 6,
      "hard_low": 6,
      "easy_low": 6
    },
    "15": {
      "hard_high": 6,
      "easy_low": 6,
      "easy_high": 6,
      "hard_low": 6
    }
  },
  "zone_counts": {
    "0": {
      "1": 6,
      "2": 6,
      "3": 6,
      "0": 6
    },
    "1": {
      "1": 6,
      "0": 6,
      "2": 6,
      "3": 6
    },
    "2": {
      "1": 6,
      "2": 6,
      "0": 6,
      "3": 6
    },
    "3": {
      "1": 6,
      "0": 6,
      "2": 6,
      "3": 6
    },
    "4": {
      "2": 6,
      "3": 6,
      "0": 6,
      "1": 6
    },
    "5": {
      "1": 6,
      "2": 6,
      "3": 6,
      "0": 6
    },
    "6": {
      "1": 6,
      "2": 6,
      "0": 6,
      "3": 6
    },
    "7": {
      "0": 6,
      "1": 6,
      "2": 6,
      "3": 6
    },
    "8": {
      "2": 6,
      "1": 6,
      "0": 6,
      "3": 6
    },
    "9": {
      "0": 6,
      "3": 6,
      "2": 6,
      "1": 6
    },
    "10": {
      "3": 6,
      "0": 6,
      "2": 6,
      "1": 6
    },
    "11": {
      "1": 6,
      "3": 6,
      "0": 6,
      "2": 6
    },
    "12": {
      "0": 6,
      "3": 6,
      "2": 6,
      "1": 6
    },
    "13": {
      "3": 6,
      "2": 6,
      "1": 6,
      "0": 6
    },
    "14": {
      "3": 6,
      "2": 6,
      "0": 6,
      "1": 6
    },
    "15": {
      "0": 6,
      "1": 6,
      "2": 6,
      "3": 6
    }
  },
  "cell_zone_tables": {
    "0": {
      "easy_low_1": 2,
      "hard_low_2": 2,
      "hard_high_3": 2,
      "easy_high_3": 2,
      "easy_low_0": 2,
      "hard_high_0": 2,
      "easy_high_2": 2,
      "hard_low_1": 2,
      "easy_low_2": 1,
      "hard_low_3": 1,
      "hard_high_2": 1,
      "easy_high_0": 1,
      "hard_high_1": 1,
      "easy_low_3": 1,
      "hard_low_0": 1,
      "easy_high_1": 1
    },
    "1": {
      "hard_low_1": 2,
      "easy_high_1": 2,
      "easy_low_0": 2,
      "hard_high_2": 2,
      "hard_low_2": 1,
      "easy_low_3": 2,
      "hard_high_3": 2,
      "hard_low_0": 2,
      "easy_high_2": 2,
      "easy_low_1": 1,
      "hard_high_1": 1,
      "hard_low_3": 1,
      "easy_low_2": 1,
      "easy_high_3": 1,
      "easy_high_0": 1,
      "hard_high_0": 1
    },
    "2": {
      "easy_high_1": 2,
      "hard_high_2": 2,
      "hard_low_2": 1,
      "easy_low_0": 1,
      "easy_high_0": 2,
      "hard_high_1": 2,
      "hard_low_0": 2,
      "easy_low_2": 2,
      "easy_high_2": 1,
      "hard_low_3": 2,
      "easy_high_3": 1,
      "hard_high_3": 1,
      "easy_low_3": 2,
      "hard_high_0": 1,
      "hard_low_1": 1,
      "easy_low_1": 1
    },
    "3": {
      "hard_high_1": 2,
      "easy_low_0": 1,
      "easy_high_2": 1,
      "hard_low_1": 1,
      "hard_high_0": 2,
      "easy_low_2": 2,
      "easy_high_3": 2,
      "hard_low_2": 2,
      "hard_high_2": 1,
      "easy_low_1": 2,
      "easy_high_1": 1,
      "hard_low_0": 1,
      "easy_high_0": 2,
      "hard_low_3": 2,
      "hard_high_3": 1,
      "easy_low_3": 1
    },
    "4": {
      "easy_low_2": 2,
      "hard_low_3": 2,
      "hard_high_2": 1,
      "easy_high_0": 2,
      "easy_low_1": 2,
      "hard_low_2": 2,
      "hard_high_0": 2,
      "easy_high_1": 1,
      "hard_low_0": 1,
      "easy_low_0": 1,
      "hard_high_1": 2,
      "easy_high_3": 2,
      "easy_low_3": 1,
      "hard_low_1": 1,
      "easy_high_2": 1,
      "hard_high_3": 1
    },
    "5": {
      "hard_low_1": 2,
      "easy_high_2": 2,
      "easy_low_3": 1,
      "hard_high_3": 2,
      "easy_high_1": 1,
      "easy_low_0": 2,
      "hard_high_0": 2,
      "hard_low_2": 2,
      "easy_high_0": 1,
      "easy_low_2": 1,
      "hard_low_3": 1,
      "easy_high_3": 2,
      "easy_low_1": 2,
      "hard_high_1": 1,
      "hard_low_0": 1,
      "hard_high_2": 1
    },
    "6": {
      "easy_high_1": 2,
      "hard_high_1": 1,
      "hard_low_1": 2,
      "easy_low_2": 1,
      "easy_high_2": 2,
      "hard_high_0": 1,
      "hard_low_3": 1,
      "easy_low_3": 2,
      "hard_high_2": 2,
      "hard_low_2": 1,
      "easy_low_1": 1,
      "easy_high_3": 1,
      "hard_high_3": 2,
      "hard_low_0": 2,
      "easy_low_0": 2,
      "easy_high_0": 1
    },
    "7": {
      "hard_high_0": 1,
      "easy_low_1": 1,
      "easy_high_2": 1,
      "hard_low_0": 2,
      "hard_high_1": 2,
      "easy_low_3": 2,
      "easy_high_1": 2,
      "hard_low_3": 2,
      "hard_high_2": 2,
      "easy_low_2": 2,
      "hard_low_2": 1,
      "hard_high_3": 1,
      "easy_high_3": 1,
      "hard_low_1": 1,
      "easy_high_0": 2,
      "easy_low_0": 1
    },
    "8": {
      "easy_low_2": 2,
      "hard_low_1": 1,
      "hard_high_2": 2,
      "easy_high_0": 2,
      "easy_low_0": 1,
      "hard_low_3": 2,
      "hard_high_1": 2,
      "easy_high_3": 1,
      "hard_low_0": 2,
      "easy_high_2": 1,
      "easy_low_3": 2,
      "hard_high_0": 1,
      "easy_high_1": 2,
      "easy_low_1": 1,
      "hard_high_3": 1,
      "hard_low_2": 1
    },
    "9": {
      "hard_low_0": 1,
      "easy_high_0": 2,
      "easy_low_3": 1,
      "hard_high_3": 1,
      "hard_low_2": 2,
      "easy_high_1": 1,
      "easy_low_1": 2,
      "hard_high_2": 1,
      "hard_low_3": 2,
      "easy_high_3": 2,
      "easy_low_2": 2,
      "hard_high_1": 2,
      "hard_low_1": 1,
      "easy_high_2": 1,
      "easy_low_0": 1,
      "hard_high_0": 2
    },
    "10": {
      "easy_high_3": 2,
      "hard_high_0": 2,
      "hard_low_0": 1,
      "easy_low_3": 1,
      "easy_high_2": 2,
      "hard_high_3": 2,
      "hard_low_1": 2,
      "easy_low_1": 2,
      "easy_high_1": 1,
      "hard_high_2": 1,
      "easy_low_2": 1,
      "easy_high_0": 1,
      "hard_low_3": 1,
      "hard_high_1": 1,
      "hard_low_2": 2,
      "easy_low_0": 2
    },
    "11": {
      "hard_high_1": 1,
      "easy_low_3": 2,
      "easy_high_0": 1,
      "hard_low_3": 1,
      "hard_high_3": 2,
      "easy_low_0": 2,
      "easy_high_1": 2,
      "hard_low_0": 2,
      "easy_high_2": 2,
      "hard_low_1": 2,
      "hard_high_2": 2,
      "easy_low_1": 1,
      "hard_low_2": 1,
      "hard_high_0": 1,
      "easy_low_2": 1,
      "easy_high_3": 1
    },
    "12": {
      "easy_low_0": 2,
      "hard_low_3": 1,
      "hard_high_2": 2,
      "easy_high_1": 2,
      "easy_low_3": 2,
      "hard_low_2": 1,
      "hard_high_1": 1,
      "easy_high_2": 2,
      "easy_low_2": 1,
      "hard_low_0": 2,
      "hard_high_3": 2,
      "easy_low_1": 1,
      "hard_low_1": 2,
      "hard_high_0": 1,
      "easy_high_0": 1,
      "easy_high_3": 1
    },
    "13": {
      "hard_low_3": 2,
      "easy_high_2": 1,
      "easy_low_3": 2,
      "hard_high_1": 2,
      "hard_low_2": 1,
      "easy_high_0": 2,
      "easy_low_2": 2,
      "hard_low_0": 2,
      "easy_high_3": 1,
      "easy_low_0": 1,
      "hard_high_2": 2,
      "easy_low_1": 1,
      "hard_high_0": 1,
      "easy_high_1": 2,
      "hard_low_1": 1,
      "hard_high_3": 1
    },
    "14": {
      "easy_high_3": 2,
      "hard_high_3": 1,
      "hard_low_2": 2,
      "easy_low_2": 2,
      "easy_high_0": 2,
      "hard_high_1": 2,
      "hard_low_3": 2,
      "easy_low_1": 2,
      "hard_low_1": 1,
      "easy_low_3": 1,
      "hard_high_2": 1,
      "easy_low_0": 1,
      "easy_high_1": 1,
      "hard_high_0": 2,
      "hard_low_0": 1,
      "easy_high_2": 1
    },
    "15": {
      "hard_high_0": 2,
      "easy_low_1": 2,
      "easy_high_2": 2,
      "hard_low_2": 2,
      "hard_high_3": 2,
      "easy_low_3": 1,
      "easy_high_3": 2,
      "hard_low_0": 1,
      "hard_high_2": 1,
      "easy_low_2": 1,
      "hard_low_1": 2,
      "hard_high_1": 1,
      "easy_high_1": 1,
      "easy_low_0": 2,
      "easy_high_0": 1,
      "hard_low_3": 1
    }
  },
  "target_exposure_check": true,
  "quick_cell_counts": {
    "0": {
      "easy_low": 2,
      "hard_low": 2,
      "hard_high": 2,
      "easy_high": 2
    },
    "1": {
      "easy_high": 2,
      "easy_low": 2,
      "hard_high": 2,
      "hard_low": 2
    },
    "2": {
      "easy_high": 2,
      "hard_high": 2,
      "easy_low": 2,
      "hard_low": 2
    },
    "3": {
      "hard_high": 2,
      "easy_low": 2,
      "easy_high": 2,
      "hard_low": 2
    },
    "4": {
      "easy_low": 2,
      "hard_low": 2,
      "hard_high": 2,
      "easy_high": 2
    },
    "5": {
      "hard_low": 2,
      "easy_high": 2,
      "easy_low": 2,
      "hard_high": 2
    },
    "6": {
      "easy_high": 2,
      "hard_high": 2,
      "easy_low": 2,
      "hard_low": 2
    },
    "7": {
      "hard_high": 2,
      "easy_low": 2,
      "easy_high": 2,
      "hard_low": 2
    },
    "8": {
      "easy_low": 2,
      "hard_low": 2,
      "hard_high": 2,
      "easy_high": 2
    },
    "9": {
      "hard_low": 2,
      "easy_high": 2,
      "easy_low": 2,
      "hard_high": 2
    },
    "10": {
      "easy_high": 2,
      "hard_high": 2,
      "hard_low": 2,
      "easy_low": 2
    },
    "11": {
      "hard_high": 2,
      "easy_low": 2,
      "easy_high": 2,
      "hard_low": 2
    },
    "12": {
      "easy_low": 2,
      "hard_low": 2,
      "hard_high": 2,
      "easy_high": 2
    },
    "13": {
      "hard_low": 2,
      "easy_high": 2,
      "easy_low": 2,
      "hard_high": 2
    },
    "14": {
      "easy_high": 2,
      "hard_high": 2,
      "hard_low": 2,
      "easy_low": 2
    },
    "15": {
      "hard_high": 2,
      "easy_low": 2,
      "easy_high": 2,
      "hard_low": 2
    }
  },
  "quick_zone_counts": {
    "0": {
      "1": 2,
      "2": 2,
      "3": 2,
      "0": 2
    },
    "1": {
      "1": 2,
      "0": 2,
      "2": 2,
      "3": 2
    },
    "2": {
      "1": 2,
      "2": 2,
      "0": 2,
      "3": 2
    },
    "3": {
      "1": 2,
      "0": 2,
      "2": 2,
      "3": 2
    },
    "4": {
      "2": 2,
      "3": 2,
      "0": 2,
      "1": 2
    },
    "5": {
      "1": 2,
      "2": 2,
      "3": 2,
      "0": 2
    },
    "6": {
      "1": 2,
      "2": 2,
      "0": 2,
      "3": 2
    },
    "7": {
      "0": 2,
      "1": 2,
      "2": 2,
      "3": 2
    },
    "8": {
      "2": 2,
      "1": 2,
      "0": 2,
      "3": 2
    },
    "9": {
      "0": 2,
      "3": 2,
      "2": 2,
      "1": 2
    },
    "10": {
      "3": 2,
      "0": 2,
      "2": 2,
      "1": 2
    },
    "11": {
      "1": 2,
      "3": 2,
      "0": 2,
      "2": 2
    },
    "12": {
      "0": 2,
      "3": 2,
      "2": 2,
      "1": 2
    },
    "13": {
      "3": 2,
      "2": 2,
      "1": 2,
      "0": 2
    },
    "14": {
      "3": 2,
      "2": 2,
      "0": 2,
      "1": 2
    },
    "15": {
      "0": 2,
      "1": 2,
      "2": 2,
      "3": 2
    }
  },
  "assistance_counts": {
    "0": {
      "readability_increase_contrast": 4,
      "readability_zoom_text": 4,
      "mixed_none": 2,
      "visual_search_highlight_region": 2,
      "mixed_highlight_region": 1,
      "readability_none": 4,
      "visual_search_zoom_text": 1,
      "mixed_zoom_text": 2,
      "visual_search_none": 2,
      "visual_search_highlight_target": 1,
      "mixed_increase_contrast": 1
    },
    "1": {
      "readability_zoom_text": 4,
      "visual_search_highlight_target": 2,
      "mixed_increase_contrast": 2,
      "readability_increase_contrast": 4,
      "visual_search_none": 1,
      "readability_none": 4,
      "visual_search_zoom_text": 1,
      "mixed_highlight_region": 1,
      "visual_search_highlight_region": 2,
      "mixed_zoom_text": 2,
      "mixed_none": 1
    },
    "2": {
      "visual_search_highlight_target": 2,
      "mixed_zoom_text": 1,
      "readability_increase_contrast": 4,
      "readability_zoom_text": 4,
      "mixed_highlight_region": 2,
      "readability_none": 4,
      "visual_search_zoom_text": 2,
      "mixed_increase_contrast": 2,
      "visual_search_highlight_region": 1,
      "mixed_none": 1,
      "visual_search_none": 1
    },
    "3": {
      "mixed_highlight_region": 2,
      "readability_none": 4,
      "visual_search_zoom_text": 2,
      "readability_zoom_text": 4,
      "mixed_increase_contrast": 1,
      "readability_increase_contrast": 4,
      "visual_search_none": 2,
      "mixed_none": 2,
      "mixed_zoom_text": 1,
      "visual_search_highlight_region": 1,
      "visual_search_highlight_target": 1
    },
    "4": {
      "readability_zoom_text": 4,
      "readability_increase_contrast": 4,
      "mixed_highlight_region": 1,
      "visual_search_none": 2,
      "readability_none": 4,
      "mixed_zoom_text": 2,
      "visual_search_highlight_region": 2,
      "mixed_increase_contrast": 1,
      "mixed_none": 2,
      "visual_search_highlight_target": 1,
      "visual_search_zoom_text": 1
    },
    "5": {
      "readability_none": 4,
      "visual_search_zoom_text": 1,
      "readability_increase_contrast": 4,
      "mixed_zoom_text": 2,
      "readability_zoom_text": 4,
      "visual_search_highlight_target": 2,
      "mixed_increase_contrast": 2,
      "visual_search_none": 1,
      "mixed_none": 1,
      "visual_search_highlight_region": 2,
      "mixed_highlight_region": 1
    },
    "6": {
      "visual_search_none": 1,
      "mixed_none": 1,
      "readability_increase_contrast": 4,
      "readability_none": 4,
      "visual_search_zoom_text": 2,
      "mixed_zoom_text": 1,
      "visual_search_highlight_region": 1,
      "mixed_highlight_region": 2,
      "readability_zoom_text": 4,
      "visual_search_highlight_target": 2,
      "mixed_increase_contrast": 2
    },
    "7": {
      "mixed_none": 2,
      "readability_zoom_text": 4,
      "visual_search_none": 2,
      "readability_increase_contrast": 4,
      "mixed_highlight_region": 2,
      "readability_none": 4,
      "visual_search_zoom_text": 2,
      "mixed_increase_contrast": 1,
      "mixed_zoom_text": 1,
      "visual_search_highlight_target": 1,
      "visual_search_highlight_region": 1
    },
    "8": {
      "readability_none": 4,
      "mixed_zoom_text": 2,
      "visual_search_highlight_region": 2,
      "readability_zoom_text": 4,
      "mixed_highlight_region": 1,
      "visual_search_zoom_text": 1,
      "readability_increase_contrast": 4,
      "mixed_none": 2,
      "visual_search_highlight_target": 1,
      "visual_search_none": 2,
      "mixed_increase_contrast": 1
    },
    "9": {
      "readability_none": 4,
      "visual_search_highlight_target": 2,
      "mixed_none": 1,
      "readability_zoom_text": 4,
      "mixed_zoom_text": 2,
      "visual_search_highlight_region": 2,
      "readability_increase_contrast": 4,
      "mixed_increase_contrast": 2,
      "visual_search_zoom_text": 1,
      "mixed_highlight_region": 1,
      "visual_search_none": 1
    },
    "10": {
      "visual_search_highlight_region": 1,
      "mixed_highlight_region": 2,
      "readability_zoom_text": 4,
      "readability_none": 4,
      "visual_search_zoom_text": 2,
      "mixed_increase_contrast": 2,
      "visual_search_none": 1,
      "mixed_zoom_text": 1,
      "readability_increase_contrast": 4,
      "visual_search_highlight_target": 2,
      "mixed_none": 1
    },
    "11": {
      "mixed_increase_contrast": 1,
      "readability_none": 4,
      "visual_search_none": 2,
      "readability_increase_contrast": 4,
      "mixed_none": 2,
      "visual_search_highlight_region": 1,
      "readability_zoom_text": 4,
      "mixed_highlight_region": 2,
      "visual_search_highlight_target": 1,
      "visual_search_zoom_text": 2,
      "mixed_zoom_text": 1
    },
    "12": {
      "readability_zoom_text": 4,
      "readability_increase_contrast": 4,
      "mixed_highlight_region": 1,
      "visual_search_none": 2,
      "readability_none": 4,
      "mixed_zoom_text": 2,
      "visual_search_highlight_region": 2,
      "mixed_increase_contrast": 1,
      "visual_search_highlight_target": 1,
      "mixed_none": 2,
      "visual_search_zoom_text": 1
    },
    "13": {
      "readability_zoom_text": 4,
      "visual_search_highlight_target": 2,
      "mixed_increase_contrast": 2,
      "readability_none": 4,
      "visual_search_zoom_text": 1,
      "readability_increase_contrast": 4,
      "mixed_zoom_text": 2,
      "visual_search_highlight_region": 2,
      "mixed_highlight_region": 1,
      "visual_search_none": 1,
      "mixed_none": 1
    },
    "14": {
      "visual_search_zoom_text": 2,
      "mixed_none": 1,
      "readability_zoom_text": 4,
      "mixed_increase_contrast": 2,
      "readability_none": 4,
      "readability_increase_contrast": 4,
      "visual_search_highlight_region": 1,
      "mixed_highlight_region": 2,
      "visual_search_highlight_target": 2,
      "visual_search_none": 1,
      "mixed_zoom_text": 1
    },
    "15": {
      "mixed_highlight_region": 2,
      "readability_zoom_text": 4,
      "visual_search_none": 2,
      "readability_none": 4,
      "mixed_increase_contrast": 1,
      "visual_search_highlight_target": 1,
      "readability_increase_contrast": 4,
      "mixed_none": 2,
      "visual_search_zoom_text": 2,
      "mixed_zoom_text": 1,
      "visual_search_highlight_region": 1
    }
  }
}

初始2×2将contrast/weight固定并逐元素记录；要比较它们应另建单因素子研究，而不是同时改变全部因素。辅助随机化与cell×zone不完全正交，小样本必须报告实际交叉表，不得宣称完美平衡。

匹配元数据修订见matching_revision.json：原始pair_id只是随机化块，现在与语义匹配族分开。该修正未改变384个UI模板、顺序、字形、目标或实际帮助分配；词库列出每个目标在16组的实际变体。完整两模式设备试跑保留旧块字段，不能将这些device-smoke用作因果研究；最终修正版额外核对匹配字段。
