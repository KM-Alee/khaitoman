/**
 * TEST FIXTURES (onboarding) — labelled, for vitest only; never imported by app code.
 * Shaped from REAL responses captured on 2026-10-10 from the dev API (127.0.0.1:8000)
 * for intake onb_5fda6c51a01441fea194181bac7d66fd (pilot-b raw bundle
 * 20261010T003841Z-798d10d2, cached Delineate run 50ca220c256bbf74, no new inference).
 * Layers are trimmed to a few features; field polygons are replaced by their bounding
 * boxes and canal lines keep their first 8 points (fixture size only).
 * `review` and `validation.publish_blockers` on the views come from this branch's
 * backend (captured read-only from a copy of the same records); `viewCreated.review`
 * and `viewNeedsReview.review` are the values that code returns for those states.
 */
/* eslint-disable */
export const ONBOARDING_FIXTURE_LABEL = "test-fixture:onboarding";

export const rawPackages = {
  "intake_kind": "raw_source_bundle",
  "packages": [
    {
      "bundle_id": "20261010T003625Z-48408f71",
      "pilot_id": "pilot-a",
      "bundle_ref": "data/raw/bundles/pilot-a/20261010T003625Z-48408f71",
      "created_at": "2026-10-10T00:37:29Z",
      "manifest_sha256": "9472bc45757d3708439089be35e06c9fffade965117f5535c62e8eb806edb317",
      "intake_kind": "raw_source_bundle",
      "aoi": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              72.33,
              30.776
            ],
            [
              72.33,
              30.798
            ],
            [
              72.306,
              30.798
            ],
            [
              72.306,
              30.776
            ],
            [
              72.33,
              30.776
            ]
          ]
        ]
      }
    },
    {
      "bundle_id": "20261010T003841Z-798d10d2",
      "pilot_id": "pilot-b",
      "bundle_ref": "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
      "created_at": "2026-10-10T00:39:41Z",
      "manifest_sha256": "5111cb539e9ce939d322e22831d70155e986492f641ec91427a0acfe913dbf2a",
      "intake_kind": "raw_source_bundle",
      "aoi": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              72.256,
              30.657
            ],
            [
              72.256,
              30.677
            ],
            [
              72.234,
              30.677
            ],
            [
              72.234,
              30.657
            ],
            [
              72.256,
              30.657
            ]
          ]
        ]
      }
    }
  ]
} as const;

export const aoiCheck = {
  "area_m2": 4679111.62,
  "bbox": [
    72.234,
    30.657,
    72.256,
    30.677
  ],
  "centroid": [
    72.24499999999999,
    30.667
  ],
  "metric_crs": "EPSG:32643",
  "estimated_pixels": 116939,
  "warnings": [],
  "blockers": [],
  "source_availability": {
    "online": "not_contacted",
    "raw_bundle_count": 2,
    "note": "Scene search happens in the process job. This check does not download."
  }
} as const;

export const aoiCheckTooBig = {
  "area_m2": 427888337.84,
  "bbox": [
    72.0,
    30.0,
    72.2,
    30.2
  ],
  "centroid": [
    72.1,
    30.1
  ],
  "metric_crs": "EPSG:32643",
  "estimated_pixels": 5024635,
  "warnings": [],
  "blockers": [
    "AOI 427.89 km² exceeds the 25 km² limit"
  ],
  "source_availability": {
    "online": "not_contacted",
    "raw_bundle_count": 2,
    "note": "Scene search happens in the process job. This check does not download."
  }
} as const;

export const viewCreated = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "intake_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "name": "Wizard capture pilot-b",
  "state": "created",
  "stage": "created",
  "review_version": 0,
  "source_mode": "raw_package",
  "bundle_ref": "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
  "pilot_id": "pilot-b",
  "pilot_version": null,
  "aoi_check": {
    "area_m2": 4679111.62,
    "bbox": [
      72.234,
      30.657,
      72.256,
      30.677
    ],
    "blockers": [],
    "centroid": [
      72.24499999999999,
      30.667
    ],
    "estimated_pixels": 116939,
    "metric_crs": "EPSG:32643",
    "warnings": []
  },
  "blockers": [],
  "warnings": [],
  "validation": {
    "blockers": [],
    "warnings": [],
    "publish_blockers": []
  },
  "job_id": null,
  "job_state": null,
  "progress": null,
  "job_stage": null,
  "error": null,
  "inference": null,
  "cache_hit": false,
  "review_summary": null,
  "created_at": "2026-10-10T11:53:18.155777Z",
  "updated_at": "2026-10-10T11:53:18.155777Z",
  "review": {
    "version": 0,
    "field_edits": [],
    "reviewer": null,
    "review_config": {},
    "network": null,
    "parent_canal_feature_id": null,
    "applied_at": null
  }
} as const;

export const processAccepted = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "job_id": "job_52652dea4603468ba1a65c6afc5756e1",
  "job": {
    "job_id": "job_52652dea4603468ba1a65c6afc5756e1",
    "operation": "onboarding.process",
    "request_hash": "1b0c4ff5bc25234bf91625ef29086a45e947503111294a1cf28a6e60010abd99",
    "state": "queued",
    "progress": null,
    "stage": null,
    "result_ref": null,
    "error": null,
    "created_at": "2026-10-10T11:53:21.846542Z",
    "updated_at": "2026-10-10T11:53:21.846542Z"
  }
} as const;

export const viewNeedsReview = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "intake_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "name": "Wizard capture pilot-b",
  "state": "needs_review",
  "stage": "needs_review",
  "review_version": 0,
  "source_mode": "raw_package",
  "bundle_ref": "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
  "pilot_id": "pilot-b",
  "pilot_version": null,
  "aoi_check": {
    "area_m2": 4679111.62,
    "bbox": [
      72.234,
      30.657,
      72.256,
      30.677
    ],
    "blockers": [],
    "centroid": [
      72.24499999999999,
      30.667
    ],
    "estimated_pixels": 116939,
    "metric_crs": "EPSG:32643",
    "warnings": []
  },
  "blockers": [],
  "warnings": [
    "S2B_43RBP_20241210_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)",
    "S2C_43RBQ_20250223_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)"
  ],
  "validation": {
    "blockers": [],
    "warnings": [
      "S2B_43RBP_20241210_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)",
      "S2C_43RBQ_20250223_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)"
    ],
    "publish_blockers": [
      "structural: direction, source, outlet, capacity and roster are not reviewed"
    ]
  },
  "job_id": "job_52652dea4603468ba1a65c6afc5756e1",
  "job_state": "succeeded",
  "progress": 0.6,
  "job_stage": "process:inference",
  "error": null,
  "inference": {
    "blockers": [],
    "cache_hit": true,
    "cache_hits": [
      "delineate:50ca220c256bbf74"
    ],
    "command": "docker compose -f compose.yaml -f vision/compose.vision.yaml --profile vision run --rm --no-deps -T vision python /app/vision/run_batch.py /app/vision/batches/50ca220c256bbf74.yaml --record /app/vision/runs/50ca220c256bbf74/run.json --label 50ca220c256bbf74",
    "device": "cpu",
    "gpkg_sha256": "34c4f40f3968d573232fcc6a71d62048941a89917380c86b33f1293ad41dceaa",
    "inference_completed": true,
    "inference_key": "50ca220c256bbf74",
    "input_sha256": "4733c68cfc3a1dcd45070824d38b8890323f005a0f349e261a707c0e85db205e",
    "parent_canal_feature_id": "osm:way/488499235",
    "review_summary": {
      "accuracy_metrics": "not_estimated: no independent reference boundaries",
      "config": {
        "aoi_inside_fraction": 0.98,
        "edge_buffer_m": 0.0,
        "fill_hole_m2": 1500.0,
        "max_area_m2": 150000.0,
        "min_area_m2": 5000.0,
        "min_compactness": 0.3,
        "min_rectangularity": 0.7,
        "min_width_m": 45.0,
        "minor_part_fraction": 0.05,
        "overlap_tolerance": 0.01,
        "target_count": 30
      },
      "eligible": 45,
      "manual_edits": 0,
      "overlap_pairs_resolved": 0,
      "raw_polygons": 303,
      "rejected": 258,
      "rules_version": "field-review-rules-1.1.0",
      "selected": 30,
      "selected_corrected": 1,
      "selected_correction_rate": 0.0333,
      "selection_method": "top-ranked eligible polygons by quality score (0.5·rectangularity + 0.3·compactness/0.785 + 0.2·log10(area)/5)"
    },
    "run_record": "vision/runs/50ca220c256bbf74/run.json",
    "warnings": [
      "S2B_43RBP_20241210_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)",
      "S2C_43RBQ_20250223_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)"
    ]
  },
  "cache_hit": true,
  "review_summary": {
    "accuracy_metrics": "not_estimated: no independent reference boundaries",
    "config": {
      "aoi_inside_fraction": 0.98,
      "edge_buffer_m": 0.0,
      "fill_hole_m2": 1500.0,
      "max_area_m2": 150000.0,
      "min_area_m2": 5000.0,
      "min_compactness": 0.3,
      "min_rectangularity": 0.7,
      "min_width_m": 45.0,
      "minor_part_fraction": 0.05,
      "overlap_tolerance": 0.01,
      "target_count": 30
    },
    "eligible": 45,
    "manual_edits": 0,
    "overlap_pairs_resolved": 0,
    "raw_polygons": 303,
    "rejected": 258,
    "rules_version": "field-review-rules-1.1.0",
    "selected": 30,
    "selected_corrected": 1,
    "selected_correction_rate": 0.0333,
    "selection_method": "top-ranked eligible polygons by quality score (0.5·rectangularity + 0.3·compactness/0.785 + 0.2·log10(area)/5)"
  },
  "created_at": "2026-10-10T11:53:18.155777Z",
  "updated_at": "2026-10-10T11:53:25.383086Z",
  "review": {
    "version": 0,
    "field_edits": [],
    "reviewer": null,
    "review_config": {},
    "network": null,
    "parent_canal_feature_id": "osm:way/488499235",
    "applied_at": null
  }
} as const;

export const viewReviewed = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "intake_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "name": "Wizard capture pilot-b",
  "state": "reviewed",
  "stage": "reviewed",
  "review_version": 1,
  "source_mode": "raw_package",
  "bundle_ref": "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
  "pilot_id": "pilot-b",
  "pilot_version": null,
  "aoi_check": {
    "area_m2": 4679111.62,
    "bbox": [
      72.234,
      30.657,
      72.256,
      30.677
    ],
    "blockers": [],
    "centroid": [
      72.24499999999999,
      30.667
    ],
    "estimated_pixels": 116939,
    "metric_crs": "EPSG:32643",
    "warnings": []
  },
  "blockers": [],
  "warnings": [],
  "validation": {
    "blockers": [],
    "warnings": [],
    "publish_blockers": []
  },
  "job_id": "job_52652dea4603468ba1a65c6afc5756e1",
  "job_state": "succeeded",
  "progress": 0.6,
  "job_stage": "process:inference",
  "error": null,
  "inference": {
    "blockers": [],
    "cache_hit": true,
    "cache_hits": [
      "delineate:50ca220c256bbf74"
    ],
    "command": "docker compose -f compose.yaml -f vision/compose.vision.yaml --profile vision run --rm --no-deps -T vision python /app/vision/run_batch.py /app/vision/batches/50ca220c256bbf74.yaml --record /app/vision/runs/50ca220c256bbf74/run.json --label 50ca220c256bbf74",
    "device": "cpu",
    "gpkg_sha256": "34c4f40f3968d573232fcc6a71d62048941a89917380c86b33f1293ad41dceaa",
    "inference_completed": true,
    "inference_key": "50ca220c256bbf74",
    "input_sha256": "4733c68cfc3a1dcd45070824d38b8890323f005a0f349e261a707c0e85db205e",
    "parent_canal_feature_id": "osm:way/488499235",
    "review_summary": {
      "accuracy_metrics": "not_estimated: no independent reference boundaries",
      "config": {
        "aoi_inside_fraction": 0.98,
        "edge_buffer_m": 0.0,
        "fill_hole_m2": 1500.0,
        "max_area_m2": 150000.0,
        "min_area_m2": 5000.0,
        "min_compactness": 0.3,
        "min_rectangularity": 0.7,
        "min_width_m": 45.0,
        "minor_part_fraction": 0.05,
        "overlap_tolerance": 0.01,
        "target_count": 30
      },
      "eligible": 45,
      "manual_edits": 0,
      "overlap_pairs_resolved": 0,
      "raw_polygons": 303,
      "rejected": 258,
      "rules_version": "field-review-rules-1.1.0",
      "selected": 30,
      "selected_corrected": 1,
      "selected_correction_rate": 0.0333,
      "selection_method": "top-ranked eligible polygons by quality score (0.5·rectangularity + 0.3·compactness/0.785 + 0.2·log10(area)/5)"
    },
    "run_record": "vision/runs/50ca220c256bbf74/run.json",
    "warnings": [
      "S2B_43RBP_20241210_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)",
      "S2C_43RBQ_20250223_0_L2A: published offset NOT applied: it would make valid pixels negative, so DNs are treated as offset-free (scale only)"
    ]
  },
  "cache_hit": true,
  "review_summary": {
    "rules_version": "field-review-rules-1.1.0",
    "config": {
      "target_count": 30,
      "min_area_m2": 5000.0,
      "max_area_m2": 150000.0,
      "min_compactness": 0.3,
      "min_width_m": 45.0,
      "min_rectangularity": 0.7,
      "fill_hole_m2": 1500.0,
      "minor_part_fraction": 0.05,
      "aoi_inside_fraction": 0.98,
      "overlap_tolerance": 0.01,
      "edge_buffer_m": 0.0
    },
    "raw_polygons": 303,
    "rejected": 259,
    "eligible": 44,
    "selected": 30,
    "selected_corrected": 1,
    "selected_correction_rate": 0.0333,
    "overlap_pairs_resolved": 0,
    "manual_edits": 1,
    "selection_method": "top-ranked eligible polygons by quality score (0.5·rectangularity + 0.3·compactness/0.785 + 0.2·log10(area)/5)",
    "accuracy_metrics": "not_estimated: no independent reference boundaries"
  },
  "review": {
    "version": 1,
    "field_edits": [
      {
        "model_id": "da:50ca220c256bbf74:237",
        "action": "reject",
        "reason": "bright bare/built-up yard; no cropped parcel boundary visible",
        "other_model_ids": []
      }
    ],
    "reviewer": "p07 wizard capture",
    "review_config": {},
    "network": {
      "direction": "downstream",
      "source_feature_id": "osm:way/488499235",
      "capacity_m3_s": 0.1,
      "roster_basis": "declared_cca",
      "outlet": "reach_group",
      "acknowledged": true
    },
    "parent_canal_feature_id": "osm:way/488499235",
    "applied_at": "2026-10-10T11:56:42Z"
  },
  "created_at": "2026-10-10T11:53:18.155777Z",
  "updated_at": "2026-10-10T11:56:42.353324Z"
} as const;

export const layersCreated = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "state": "created",
  "available": [
    "aoi"
  ],
  "unavailable": [
    {
      "id": "imagery",
      "reason": "not available until processing writes it"
    },
    {
      "id": "canals",
      "reason": "not available until processing writes it"
    },
    {
      "id": "fields-raw",
      "reason": "not available until processing writes it"
    },
    {
      "id": "fields-proposed",
      "reason": "not available until processing writes it"
    },
    {
      "id": "terrain",
      "reason": "not available until processing writes it"
    },
    {
      "id": "weather",
      "reason": "not available until processing writes it"
    }
  ]
} as const;

export const layersReady = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "state": "needs_review",
  "available": [
    "aoi",
    "imagery",
    "canals",
    "fields-raw",
    "fields-proposed",
    "terrain",
    "weather"
  ],
  "unavailable": []
} as const;

export const layerAoi = {
  "layer_id": "aoi",
  "geojson": {
    "type": "Polygon",
    "coordinates": [
      [
        [
          72.256,
          30.657
        ],
        [
          72.256,
          30.677
        ],
        [
          72.234,
          30.677
        ],
        [
          72.234,
          30.657
        ],
        [
          72.256,
          30.657
        ]
      ]
    ]
  },
  "source": "intake"
} as const;

export const layerImagery = {
  "layer_id": "imagery",
  "scenes": [
    {
      "scene_id": "S2B_43RBP_20241210_0_L2A",
      "label": "secondary",
      "collection": "sentinel-2-l2a",
      "acquired_at": "2024-12-10T06:00:40.147000Z",
      "resolution_m": 10.0,
      "aoi_valid_fraction": 1.0,
      "scene_cloud_cover": 0.000378,
      "width": 345,
      "height": 357,
      "assets": {
        "red": {
          "key": "red",
          "gsd": 10.0
        },
        "green": {
          "key": "green",
          "gsd": 10.0
        },
        "blue": {
          "key": "blue",
          "gsd": 10.0
        },
        "nir": {
          "key": "nir",
          "gsd": 10.0
        },
        "scl": {
          "key": "scl",
          "gsd": 20.0
        }
      }
    }
  ]
} as const;

export const layerCanals = {
  "layer_id": "canals",
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "id": "osm:way/488499235",
        "geometry": {
          "type": "LineString",
          "coordinates": [
            [
              72.274623,
              30.846811
            ],
            [
              72.272946,
              30.846349
            ],
            [
              72.272139,
              30.846124
            ],
            [
              72.26803,
              30.844907
            ],
            [
              72.264715,
              30.843985
            ],
            [
              72.26407,
              30.843672
            ],
            [
              72.263603,
              30.843335
            ],
            [
              72.263183,
              30.842717
            ]
          ]
        },
        "properties": {
          "source_feature_id": "osm:way/488499235",
          "provider": "osm",
          "osm_type": "way",
          "osm_id": 488499235,
          "waterway": "canal",
          "name": "R-1",
          "observed": true,
          "license": "ODbL-1.0"
        }
      },
      {
        "type": "Feature",
        "id": "osm:way/863144483",
        "geometry": {
          "type": "LineString",
          "coordinates": [
            [
              72.14614,
              31.145094
            ],
            [
              72.15168,
              31.144032
            ],
            [
              72.155938,
              31.143182
            ],
            [
              72.160794,
              31.142263
            ],
            [
              72.168847,
              31.140716
            ],
            [
              72.170674,
              31.140326
            ],
            [
              72.171797,
              31.140035
            ],
            [
              72.172659,
              31.13973
            ]
          ]
        },
        "properties": {
          "source_feature_id": "osm:way/863144483",
          "provider": "osm",
          "osm_type": "way",
          "osm_id": 863144483,
          "waterway": "canal",
          "name": "Link Lower Trimmu-Sidhnai Canal",
          "observed": true,
          "license": "ODbL-1.0"
        }
      },
      {
        "type": "Feature",
        "id": "grain:PAK_456427_00120",
        "geometry": {
          "type": "MultiLineString",
          "coordinates": [
            [
              [
                72.27462,
                30.846811
              ],
              [
                72.272949,
                30.84635
              ]
            ],
            [
              [
                72.272949,
                30.84635
              ],
              [
                72.272141,
                30.846125
              ]
            ]
          ]
        },
        "properties": {
          "source_feature_id": "grain:PAK_456427_00120",
          "provider": "grain",
          "observed": true,
          "license": "CC-BY-4.0"
        }
      }
    ]
  }
} as const;

export const layerProposed = {
  "layer_id": "fields-proposed",
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "id": "pilot-b:field-001",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.247077,
                30.673371
              ],
              [
                72.250479,
                30.673371
              ],
              [
                72.250479,
                30.676221
              ],
              [
                72.247077,
                30.676221
              ],
              [
                72.247077,
                30.673371
              ]
            ]
          ]
        },
        "properties": {
          "field_id": "pilot-b:field-001",
          "label": "B-001",
          "area_m2": 44087.49999993888,
          "source_model_ids": [
            "da:50ca220c256bbf74:237"
          ],
          "actions": []
        }
      },
      {
        "type": "Feature",
        "id": "pilot-b:field-002",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.251985,
                30.672854
              ],
              [
                72.255322,
                30.672854
              ],
              [
                72.255322,
                30.675379
              ],
              [
                72.251985,
                30.675379
              ],
              [
                72.251985,
                30.672854
              ]
            ]
          ]
        },
        "properties": {
          "field_id": "pilot-b:field-002",
          "label": "B-002",
          "area_m2": 40600.000000064756,
          "source_model_ids": [
            "da:50ca220c256bbf74:415"
          ],
          "actions": []
        }
      },
      {
        "type": "Feature",
        "id": "pilot-b:field-003",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.237981,
                30.672903
              ],
              [
                72.239804,
                30.672903
              ],
              [
                72.239804,
                30.674221
              ],
              [
                72.237981,
                30.674221
              ],
              [
                72.237981,
                30.672903
              ]
            ]
          ]
        },
        "properties": {
          "field_id": "pilot-b:field-003",
          "label": "B-003",
          "area_m2": 16156.24999989508,
          "source_model_ids": [
            "da:50ca220c256bbf74:266"
          ],
          "actions": []
        }
      }
    ]
  }
} as const;

export const layerRaw = {
  "layer_id": "fields-raw",
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "id": "da:50ca220c256bbf74:237",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.247077,
                30.673371
              ],
              [
                72.250479,
                30.673371
              ],
              [
                72.250479,
                30.676221
              ],
              [
                72.247077,
                30.676221
              ],
              [
                72.247077,
                30.673371
              ]
            ]
          ]
        },
        "properties": {
          "model_id": "da:50ca220c256bbf74:237",
          "gpkg_fid": 237,
          "id": 237,
          "bg": false,
          "area": 44047.21484375
        }
      },
      {
        "type": "Feature",
        "id": "da:50ca220c256bbf74:266",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.237981,
                30.672903
              ],
              [
                72.239804,
                30.672903
              ],
              [
                72.239804,
                30.674221
              ],
              [
                72.237981,
                30.674221
              ],
              [
                72.237981,
                30.672903
              ]
            ]
          ]
        },
        "properties": {
          "model_id": "da:50ca220c256bbf74:266",
          "gpkg_fid": 266,
          "id": 266,
          "bg": false,
          "area": 16141.287109375
        }
      },
      {
        "type": "Feature",
        "id": "da:50ca220c256bbf74:415",
        "geometry": {
          "type": "Polygon",
          "coordinates": [
            [
              [
                72.251985,
                30.672854
              ],
              [
                72.255322,
                30.672854
              ],
              [
                72.255322,
                30.675379
              ],
              [
                72.251985,
                30.675379
              ],
              [
                72.251985,
                30.672854
              ]
            ]
          ]
        },
        "properties": {
          "model_id": "da:50ca220c256bbf74:415",
          "gpkg_fid": 415,
          "id": 415,
          "bg": false,
          "area": 40563.15234375
        }
      }
    ]
  }
} as const;

export const layerWeather = {
  "layer_id": "weather",
  "weather": {
    "weather_series_id": "openmeteo-archive-30.7000N-72.2000E-20140101-20251231",
    "point_requested": [
      30.667,
      72.245
    ],
    "point_returned": [
      30.700005,
      72.2
    ],
    "elevation_m": 142.0,
    "start": "2014-01-01",
    "end": "2025-12-31",
    "complete_years": [
      2014,
      2015,
      2016,
      2017,
      2018,
      2019,
      2020,
      2021,
      2022,
      2023,
      2024,
      2025
    ],
    "source_model": "era5_seamless",
    "raw_ref": "weather/openmeteo-archive-30.7000N-72.2000E-20140101-20251231.json",
    "normalized_ref": "weather/openmeteo-archive-30.7000N-72.2000E-20140101-20251231.parquet",
    "source_sha256": "c49501f2132cc2ae4389e5af2646352d3771d7e5abf3d572f1defc5cb4d98b37",
    "normalized_sha256": "9bffb5ade11d4a83fe71bbda9157899b3e779b5853337ba02ac3ba80a1286cb5",
    "retrieved_at": "2026-10-10T00:39:39Z",
    "source_url": "https://archive-api.open-meteo.com/v1/archive?latitude=30.66700&longitude=72.24500&start_date=2014-01-01&end_date=2025-12-31&daily=temperature_2m_min%2Ctemperature_2m_max%2Cprecipitation_sum%2Cet0_fao_evapotranspiration&timezone=Asia%2FKarachi&temperature_unit=celsius&precipitation_unit=mm&timeformat=iso8601&models=era5_seamless",
    "units": {
      "MinTemp": "°C",
      "MaxTemp": "°C",
      "Precipitation": "mm",
      "ReferenceET": "mm"
    },
    "timezone": "Asia/Karachi",
    "generationtime_ms": 999.6238946914673,
    "rows": 4383
  }
} as const;

export const layerTerrain = {
  "layer_id": "terrain",
  "metadata": {
    "image_ref": "terrain/dem.png",
    "bounds": [
      72.22375,
      30.64708333,
      72.26569444,
      30.68708333
    ],
    "width": 151,
    "height": 144,
    "min_m": 137.24600219726562,
    "max_m": 149.88845825195312,
    "encoding": "terrarium",
    "decode": "height_m = (R*256 + G + B/256) - 32768",
    "crs": "EPSG:4326",
    "source_url": "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N30_00_E072_00_DEM/Copernicus_DSM_COG_10_N30_00_E072_00_DEM.tif",
    "source_sha256": "ef822fdcc1c133b27e9a1d502ed1abdc1e693267e27e3512ce16d5802418759b",
    "resolution_deg": [
      0.0002777777777777778,
      0.0002777777777777778
    ],
    "note": "Display context only; slope does not verify canal flow direction."
  }
} as const;

export const reviewOk = {
  "onboarding_id": "onb_5fda6c51a01441fea194181bac7d66fd",
  "review_version": 1,
  "state": "reviewed",
  "blockers": [],
  "warnings": []
} as const;

export const reviewConflict = {
  "code": "VERSION_CONFLICT",
  "detail": "review version 1 != expected 0",
  "fields": {},
  "dependency_diff": {
    "review_version": 1,
    "expected_version": 0
  }
} as const;

export const reviewInvalid = {
  "code": "INVALID_INPUT",
  "detail": "field edit da:50ca220c256bbf74:237 needs a reason",
  "fields": {
    "review": "field edit da:50ca220c256bbf74:237 needs a reason"
  }
} as const;

export const publishExists = {
  "code": "VERSION_CONFLICT",
  "detail": "pilot-b/reviewed-v1 is already published and cannot be replaced",
  "fields": {},
  "dependency_diff": {
    "pilot_id": "pilot-b",
    "pilot_version": "reviewed-v1",
    "immutable": true
  }
} as const;

export const publishNoVersion = {
  "code": "INVALID_INPUT",
  "detail": "pilot_version is required",
  "fields": {
    "pilot_version": "required"
  }
} as const;

