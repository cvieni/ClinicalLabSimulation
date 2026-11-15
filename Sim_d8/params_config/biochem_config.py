"""Which bench tests run for which specimen type, and how often.  EDIT THIS FILE to change a percentage or a pathway.

Each step:  {"test": name, "p": P(test is performed | the step is reached), ...options}
  requires_prev : only run if the previous test in the list was performed AND positive   (e.g. TSI only after a positive oxidase)
  scope         : "specimen" (default) = the test is done on ONE isolate of the specimen with probability p (your "x % of cultures");
                  "isolate"  = every isolate gets its own draw with probability p (n isolates -> up to n tests)
  parallel      : True = the test is started in the background and runs alongside MALDI/AST; the specimen waits for it only
                  before the final read (TSI on routine stool).  Parallel steps cannot gate MALDI (no on_negative/requires_prev).
  bench         : who runs the test.  Default = the tech who read the plate (presumptive) / the type's own bench (post_id: bottles ->
                  tech_blood, urine -> tech_urine, stool -> tech_stool, everything else -> routine side).
                  Override per step: "processor" | "type" | "routine" | a resource key such as "tech_urine".
  at_read       : True = run the test at the plate read even if the plate has been incubated twice or more (default False: see the rule below)
  RULE (presumptive phase): the tech who READ the plate runs the test right away only if the isolate is on its first plate and that plate has
                  not been incubated twice (a re-incubated plate, or a configured hold of 48 h or more, counts as 2+).  Otherwise the test is deferred
                  to the isolate's next plate (a subculture, set up if none was planned) and run by whoever reads that plate after one incubation.
  on_negative   : "stop" -> a negative result closes the culture (logged as a discard, counted as culture-negative); default "continue"

Phases (see specimen_process_d5.py):
  presumptive : after the plate read / repeat work-up, BEFORE MALDI.  A "stop" here skips MALDI and AST.
  post_id     : after MALDI identified >= 1 isolate, BEFORE Phoenix AST.

Tests: oxidase, tsi, indole, catalase, pbp (PBP2a lateral flow), latex (E. coli agglutination), biochem_panel (oxidase+catalase+indole+urease
bundle, uses p.min/max_biochem_screen_time).  Times, TSI incubation, and per-test positive rates are parameters in params_d3.py
(or per-specimen-type overrides inside SPECIMEN_TYPES[type], see the stool blocks in specimen_config_d2.py).

Percentages marked [GIVEN] came from you; [GUESS] are placeholders to set from your SOPs/LIS.
"""
T = lambda test, p=1.0, **kw: {"test": test, "p": p, **kw}

BIOCHEM_PLAN = {
    # ---- stools (four configs) --------------------------------------------------------------------
    "Stool_EcoliRoutine": {"presumptive": [T("oxidase", 1.0),          # [GIVEN] sweep oxidase 100 %
                                           T("tsi", 0.10, parallel=True)],  # [GIVEN] TSI 10 %, runs in parallel with MALDI
                           "post_id":     [T("latex", 1.0)]},         # [GUESS] E. coli latex after MALDI (from your notes); share of ID'd isolates
    "Stool_Campy":        {},                                          # CVA 72 h hold only (config); no bench tests requested
    "Stool_Vibrio":       {"presumptive": [T("oxidase", 1.0, on_negative="stop"),            # SOP notes: oxidase -> if positive TSI -> K/A continues
                                           T("tsi", 1.0, requires_prev=True, on_negative="stop")]},
    "Stool_Yersinia":     {"presumptive": [T("tsi", 1.0),              # TSI + 2 MIO tubes set up together (config: 3-7 min), 18-24 h
                                           T("biochem_panel", 1.0)]},  # oxidase / catalase / indole / urease read after the tubes
    # ---- urine ------------------------------------------------------------------------------------
    "Urine_Invasive":     {"presumptive": [T("indole", 0.90)]},        # [GIVEN] 90 %
    "Urine_NonInvasive":  {"presumptive": [T("indole", 0.90)]},        # [GIVEN] 90 %
    # ---- blood / wound ----------------------------------------------------------------------------
    "BCx":                {"presumptive": [T("catalase", 0.25)],       # [GIVEN] catalase 25 % of positive blood cultures
                           "post_id":     [T("pbp", 0.25)]},          # [GIVEN] PBP2a lateral flow 25 %, once an isolate is identified
    "Wound":              {"post_id":     [T("pbp", 0.25)]},          # [GIVEN] 25 %
    "Wound_Genital":      {"post_id":     [T("pbp", 0.25)]},          # remove this line if genital wounds should not get PBP2a
}

# your config names this type "Stool_Ecoli" (older drafts: "Stool_EcoliRoutine"): same plan for both
BIOCHEM_PLAN["Stool_Ecoli"] = BIOCHEM_PLAN["Stool_EcoliRoutine"]
