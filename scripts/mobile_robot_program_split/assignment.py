"""Which library program each Main function moves into.

`DROP` marks the three dispatcher ladders plus the old entry point: their job moves
to the Python routing table and the generated thin entry programs, so they are not
carried over.
"""

from __future__ import annotations

SHARED = "Shared"
LABMAN = "Station_Labman"
BFT = "Station_BFT"
DASH = "Station_DASH"
SRS = "Station_SRS"
IXRD = "Station_IXRD"
SEMEDS = "Station_SEMEDS"
ON_ROBOT = "On_Robot"
TESTS = "Tests"
DROP = "<dropped>"

LIBRARIES = (SHARED, LABMAN, BFT, DASH, SRS, IXRD, SEMEDS, ON_ROBOT, TESTS)

ASSIGNMENT: dict[str, str] = {
    # Replaced by the Python routing table and the thin entry programs.
    "Main_program": DROP,
    "BaseHandler": DROP,
    "PickHandler": DROP,
    "PlaceHandler": DROP,
    # Cross-cutting helpers and the home/charge primitives.
    "LoadAllVariables": SHARED,
    "PickPlaceErrorHandling": SHARED,
    "EnsureCalibratedWithStation": SHARED,
    "ResetTagCalibrations": SHARED,
    "HomeBase": SHARED,
    "HomeRobotArm": SHARED,
    "Charging": SHARED,
    # LABMAN
    "Go to Labman": LABMAN,
    "Out from Labman": LABMAN,
    "GetIntoLabman": LABMAN,
    "MoveIntoLabmanWithRack": LABMAN,
    "MoveOutFromLabmanWithRack": LABMAN,
    "MoveToLabmanBackApproach": LABMAN,
    "MoveToBeforeLabmanBackApproach": LABMAN,
    "LABMANCalibrateAndGoHome": LABMAN,
    "LABMANRecoveryPickPlace": LABMAN,
    "LABMAN BASE ERROR RECOVERY": LABMAN,
    "CheckAllLABMANWaypointsReachability": LABMAN,
    "PickCrucibleRackAOnLABMAN": LABMAN,
    "PickCrucibleRackBOnLABMAN": LABMAN,
    "PickCrucibleRackCOnLABMAN": LABMAN,
    "PickCrucibleRackDOnLABMAN": LABMAN,
    "PlaceCrucibleRackAOnLABMAN": LABMAN,
    "PlaceCrucibleRackBOnLABMAN": LABMAN,
    "PlaceCrucibleRackCOnLABMAN": LABMAN,
    "PlaceCrucibleRackDOnLABMAN": LABMAN,
    # BFT / furnace station
    "Go To Furnace Station": BFT,
    "Out From Furnace Station": BFT,
    "BFT_PICK": BFT,
    "BFT_PLACE": BFT,
    "BFTRecoveryPickPlace": BFT,
    "Check and Calibrate FurnaceStation": BFT,
    "Workbench Marker Calibration": BFT,
    "Workbench Marker Calibration for Moving Base": BFT,
    # DASH
    "Go To DASH": DASH,
    "OutFromDASH_New": DASH,
    "DASH_PICK": DASH,
    "DASH_PLACE": DASH,
    "DASHRecoveryPickPlace": DASH,
    "Calibrate DASH Tag": DASH,
    "Check and Calibrate DASH Tag": DASH,
    # SubRack storage station
    "Go To SubRackStorage Station": SRS,
    "Out From SubRackStorageStation": SRS,
    "Check and Calibrate SRS": SRS,
    "SRSRecoveryPickPlace": SRS,
    "SubRackStorage Station Calibration For Moving Base": SRS,
    "SubRackStorage Station Workbench Calibration": SRS,
    "PickCrucibleRackAOnSRS": SRS,
    "PickCrucibleRackBOnSRS": SRS,
    "PickCrucibleRackCOnSRS": SRS,
    "PickCrucibleRackDOnSRS": SRS,
    "PlaceCrucibleRackAOnSRS": SRS,
    "PlaceCrucibleRackBOnSRS": SRS,
    "PlaceCrucibleRackCOnSRS": SRS,
    "PlaceCrucibleRackDOnSRS": SRS,
    # In-situ XRD
    "GoToIXRDStation": IXRD,
    "Out from IXRD": IXRD,
    "Check and Calibrate IXRD": IXRD,
    "CheckIXRDWaypoint": IXRD,
    "CalibrateIXRDtags": IXRD,
    "IXRD BASE ERROR RECOVERY_1": IXRD,
    "IXRD BASE ERROR RECOVERY_2": IXRD,
    "ReorientIXRDVertically": IXRD,
    "PlaceSubrackAIXRD": IXRD,
    "PlaceSubrackBIXRD": IXRD,
    "PlaceSubrackCIXRD": IXRD,
    "PlaceSubrackDIXRD": IXRD,
    # SEM/EDS
    "GoToSEMEDS": SEMEDS,
    "Out from SEMEDS": SEMEDS,
    "PlaceSEMEDSRack": SEMEDS,
    "PickSEMRackVerticalOnRobot_SEMEDS": SEMEDS,
    "SEMEDS BASE ERROR RECOVERY_1": SEMEDS,
    "SEMEDS BASE ERROR RECOVERY_2": SEMEDS,
    # Everything that happens on the robot's own deck
    "ROBOT_BASE_PICK_SUBRACK": ON_ROBOT,
    "ROBOT_BASE_PLACE_SUBRACK": ON_ROBOT,
    "RecoveryRobotBasePickPlace": ON_ROBOT,
    "ReorientCrucibleRackVertically": ON_ROBOT,
    "PickCrucibleRackAOnRobot": ON_ROBOT,
    "PickCrucibleRackBOnRobot": ON_ROBOT,
    "PickCrucibleRackCOnRobot": ON_ROBOT,
    "PickCrucibleRackDOnRobot": ON_ROBOT,
    "PlaceCrucibleRackAOnRobot": ON_ROBOT,
    "PlaceCrucibleRackBOnRobot": ON_ROBOT,
    "PlaceCrucibleRackCOnRobot": ON_ROBOT,
    "PlaceCrucibleRackDOnRobot": ON_ROBOT,
    "PickCrucibleRackAVerticalOnRobot": ON_ROBOT,
    "PickCrucibleRackBVerticalOnRobot": ON_ROBOT,
    "PickCrucibleRackCVerticalOnRobot": ON_ROBOT,
    "PickCrucibleRackDVerticalOnRobot": ON_ROBOT,
    "PlaceCrucibleRackAVerticalOnRobot": ON_ROBOT,
    "PlaceCrucibleRackBVerticalOnRobot": ON_ROBOT,
    "PlaceCrucibleRackCVerticalOnRobot": ON_ROBOT,
    "PlaceCrucibleRackDVerticalOnRobot": ON_ROBOT,
    "PickCrucibleRackAVerticalOnRobot_IXRD": ON_ROBOT,
    "PickCrucibleRackBVerticalOnRobot_IXRD": ON_ROBOT,
    "PickCrucibleRackCVerticalOnRobot_IXRD": ON_ROBOT,
    "PickCrucibleRackDVerticalOnRobot_IXRD": ON_ROBOT,
    # Orphaned test / soak / legacy, per the plan
    "CalibrateSEMEDStags": TESTS,
    "Check and Calibrate SEMEDS": TESTS,
    "CheckSEMEDSWaypoint": TESTS,
    "Function 95": TESTS,
    "FurnaceStationTagFromPrometheusTagCalculation": TESTS,
    "IXRD_Test": TESTS,
    "MoveToAlignedWithDASH": TESTS,
    "MoveToAlignedWithLabman": TESTS,
    "MoveToLABMAN": TESTS,
    "OutFromDASH_Old": TESTS,
    "Prometheus Marker Calibration": TESTS,
    "RefillCrucibleRackA": TESTS,
    "RefillCrucibleRackB": TESTS,
    "RefillCrucibleRackC": TESTS,
    "RefillCrucibleRackD": TESTS,
    "ReorientSEMEDSVertically": TESTS,
    "SoakTesstIXRD": TESTS,
    "SoakTestSEMEDS": TESTS,
    "TEST Labman": TESTS,
    "Test 1 Labman": TESTS,
    "Test 2 Labman": TESTS,
    "Test 3 Labman": TESTS,
    # Grid maths. Copied into each consuming library rather than shared: its callers
    # pass x_dim / offset_x / offset_y / GridOrigin in through variables, so producer
    # and consumer must sit in one program whether or not includes share scope.
    "GridCompute": BFT,
    "Calculate rows and columns": BFT,
}

# Functions copied into libraries beyond their primary home. Their call closure is
# copied with them.
ALSO_IN: dict[str, tuple[str, ...]] = {
    "GridCompute": (DASH, ON_ROBOT),
    "Calculate rows and columns": (DASH, ON_ROBOT),
}
