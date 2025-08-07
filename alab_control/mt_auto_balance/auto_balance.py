from __future__ import annotations

import abc
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import List, Literal, Type, TypeVar

import zeep
from pydantic import BaseModel
from zeep.helpers import serialize_object

from alab_control.mt_auto_balance.cryptography_helper import decrypt_session_id

all_services = [
    "SessionService",
    "WeighingService",
    "WeighingTaskService",
    "UserInteractionService",
    "ToleranceProfileService",
    "RoutineTestService",
    "NotificationService",
    "FeederService",
    "DraftShieldsService",
    "DosingAutomationService",
    "BasicService",
    "AuthenticationService",
    "AdjustmentService",
]

logger = logging.getLogger("auto_balance")


class MTAutoBalanceError(Exception):
    pass


class WeightWithUnit(BaseModel):
    """
    Example weight with unit:

    {
        'Value': 0.00015,
        'Unit': 'Gram',
        'CustomUnitName': None
    }
    """

    Value: Decimal | None
    Unit: str
    CustomUnitName: str | None = None
    PreTare: bool | None = None

    def get_weight_gram(self):
        """
        Convert the weight to gram.
        """
        if self.Unit == "Gram":
            return float(self.Value)
        elif self.Unit == "Kilogram":
            return float(self.Value) * 1000
        elif self.Unit == "Milligram":
            return float(self.Value) / 1000
        else:
            raise ValueError(f"Unknown unit: {self.Unit}")


class BalanceWeightResult(BaseModel):
    """
    Example result of the balance weight:

    {
         'NetWeight': {
             'Value': '0.00015',
             'Unit': 'Gram',
             'CustomUnitName': None
         },
         'GrossWeight': {
             'Value': '0.00325',
             'Unit': 'Gram',
             'CustomUnitName': None
         },
         'TareWeight': {
             'Value': '0.00310',
             'Unit': 'Gram',
             'CustomUnitName': None,
             'PreTare': False
         },
         'Stable': True,
         'Status': 'Ok'
     }
    """

    NetWeight: WeightWithUnit | None
    GrossWeight: WeightWithUnit | None
    TareWeight: WeightWithUnit | None
    Stable: bool
    Status: str


class BaseClient(abc.ABC):
    name: str
    wsdl: Path = Path(__file__).parent / "MT.Laboratory.Balance.XprXsr.V03.wsdl"

    def __init__(self, host: str, session: "Session" = None):
        self.client = zeep.Client(wsdl=self.wsdl.as_posix())
        self.session = session
        self.service = self.client.create_service(
            binding_name=f"{{http://MT/Laboratory/Balance/XprXsr/V03}}BasicHttpBinding_I{self.name}",
            address=host.rstrip("/") + "/MT/Laboratory/Balance/XprXsr/V03",
        )

    def check_response(self, response):
        if response["Outcome"] != "Success":
            raise MTAutoBalanceError(
                f"{self.name} failed. The error message is: {response['ErrorMessage']}"
            )


class SessionClient(BaseClient):
    name = "SessionService"

    def open_session(self, password: str) -> str:
        response = self.service.OpenSession()
        self.check_response(response)

        return decrypt_session_id(
            encrypted_session_id=response["SessionId"],
            password=password,
            encoded_salt=response["Salt"],
        )

    def close_session(self, session_id: str):
        response = self.service.CloseSession(SessionId=session_id)
        self.check_response(response)


class WeighingClient(BaseClient):
    name = "WeighingService"

    def get_weight(
        self,
        weight_capture_mode: Literal[
            "Stable", "Immediate", "TimeInterval", "WeightChange"
        ] = "Stable",
    ) -> BalanceWeightResult:
        """
        Get weight from the balance.

        Example:
        {
            'NetWeight': {
                'Value': '0.00000',
                'Unit': 'Gram',
                'CustomUnitName': None
            },
            'GrossWeight': {
                'Value': '0.00000',
                'Unit': 'Gram',
                'CustomUnitName': None
            },
            'TareWeight': None,
            'Stable': True,
            'Status': 'Ok'
        }
        """
        session_id = self.session.session_id
        response = self.service.GetWeight(
            SessionId=session_id, WeighingCaptureMode=weight_capture_mode
        )
        self.check_response(response)
        return BalanceWeightResult(**serialize_object(response["WeightSample"]))

    def tare(self, tare_immediately: bool = False):
        session_id = self.session.session_id
        response = self.service.Tare(
            SessionId=session_id, TareImmediately=tare_immediately
        )
        self.check_response(response)

    def zero(self, zero_immediately: bool = False):
        session_id = self.session.session_id
        response = self.service.Zero(
            SessionId=session_id, ZeroImmediately=zero_immediately
        )
        self.check_response(response)


class WeightingTaskClient(BaseClient):
    name = "WeighingTaskService"

    def set_target_value_and_tolerances(
        self,
        target_value_g: float,
        lower_tolerance_percent: float,
        upper_tolerance_percent: float,
    ):
        session_id = self.session.session_id
        response = self.service.SetTargetValueAndTolerances(
            SessionId=session_id,
            TargetWeight={
                "Value": target_value_g,
                "Unit": "Gram",
            },
            LowerTolerance={
                "Value": lower_tolerance_percent,
                "Unit": "Percent",
            },
            UpperTolerance={
                "Value": upper_tolerance_percent,
                "Unit": "Percent",
            },
        )
        self.check_response(response)

    def start_weighing_task(self, method="Dosing"):
        session_id = self.session.session_id
        response = self.service.StartTask(SessionId=session_id, MethodName=method)
        self.check_response(response)

    def get_weighing_methods(self) -> list:
        """
        Example:
        [
            {
                'Name': 'General Weighing',
                'MethodType': 'GeneralWeighing'
            },
            {
                'Name': 'Dosing',
                'MethodType': 'AutomatedDosing'
            }
        ]
        """
        session_id = self.session.session_id
        response = self.service.GetListOfMethods(SessionId=session_id)
        self.check_response(response)
        return response["Methods"]["MethodDescription"]


class DosingAutomationClient(BaseClient):
    name = "DosingAutomationService"

    def read_dosing_head(self) -> dict:
        """
        Get information about the dosing head.

        Example:
        {
            'Outcome': 'Success',
            'ErrorMessage': None,
            'HeadType': 'Powder',
            'HeadTypeName': 'QH012-LNJW',
            'HeadId': '063161107153',
            'DosingHeadInfo': {
                'SubstanceName': '??',
                'LotId': '??',
                'FillingDate': None,
                'ExpiryDate': None,
                'Id1Label': 'Var 1',
                'Id1Value': 'Value 1',
                'Id2Label': 'Var 2',
                'Id2Value': 'Value 2',
                'Id3Label': 'Var 3',
                'Id3Value': 'Value 3',
                'MolarMass': None,
                'Purity': None,
                'FilledUpQuantity': None,
                'TappingWhileDosing': True,
                'TappingBeforeDosing': False,
                'DosingLimit': 250,
                'DensityOfLiquid': None,
                'PumpPressure': None,
                'RemainingQuantity': None,
                'NumberOfDosages': 3,
                'RemainingDosages': 247
            }
        }

        """
        session_id = self.session.session_id
        with self.client.settings(
            strict=False
        ):  # the response is not strictly following the schema
            response = self.service.ReadDosingHead(SessionId=session_id)
        self.check_response(response)
        return response

    def start_dosing(
        self,
        substance_name: str,
        vial_name: str,
        target_value_g: float,
        lower_tolerance_percent: float,
        upper_tolerance_percent: float,
    ):
        session_id = self.session.session_id
        response = self.service.StartExecuteDosingJobListAsync(
            SessionId=session_id,
            DosingJobList={
                "DosingJob": [
                    {
                        "SubstanceName": substance_name,
                        "VialName": vial_name,
                        "TargetWeight": {
                            "Value": round(target_value_g, 5),
                            "Unit": "Gram",
                        },
                        "LowerTolerance": {
                            "Value": lower_tolerance_percent,
                            "Unit": "Percent",
                        },
                        "UpperTolerance": {
                            "Value": upper_tolerance_percent,
                            "Unit": "Percent",
                        },
                    }
                ]
            },
        )
        try:
            self.check_response(response)
        except MTAutoBalanceError as e:
            e.args = (f"{e.args[0]} The raw response is {response}",)
            raise e

    def confirm_dosing_job_action(
        self,
        dosing_job_action: Literal[
            "PlaceDosingHead", "RemoveDosingHead", "PlaceVial", "RemoveVial"
        ],
        action_item: str,
    ):
        session_id = self.session.session_id
        response = self.service.ConfirmDosingJobAction(
            SessionId=session_id,
            ExecutedDosingJobAction=dosing_job_action,
            ActionItem=action_item,
        )
        self.check_response(response)


class NotificationClient(BaseClient):
    name = "NotificationService"

    def get_notifications(self, long_polling_timeout: int = 1000) -> list:
        """
        Example:
        [{'DosingAutomationActionAsyncNotification': {
            'CommandId': 1,
            'Outcome': 'Success',
            'DosingJobActionType': 'PlaceVial',
            'DosingJobActionReason': 'DosingJobSetup',
            'ActionItem': 'Vial',
            'DosingHeadError': None
        }}]
        """
        session_id = self.session.session_id
        with self.client.settings(strict=False):
            response = self.service.GetNotifications(
                SessionId=session_id, LongPollingTimeout=long_polling_timeout
            )
        try:
            self.check_response(response)
        except MTAutoBalanceError:
            if "GetNotifications has timed out." in response["ErrorMessage"]:
                return []

        logger.info(response["Notifications"]["_value_1"])
        return response["Notifications"]["_value_1"]


class DraftShieldsClient(BaseClient):
    name = "DraftShieldsService"

    def get_door_position(
        self, doors: list = ("LeftOuter", "RightOuter")
    ) -> List[dict]:
        """
        Example:
        [{
            'DraftShieldId': 'LeftOuter',
            'OpeningWidth': 0,
            'OpeningSide': None,
            'Description': 'left outer door',
            'PositionDeterminationOutcome': 'Success'
        }, {
            'DraftShieldId': 'RightOuter',
            'OpeningWidth': 0,
            'OpeningSide': None,
            'Description': 'right outer door',
            'PositionDeterminationOutcome': 'Success'
        }]
        """
        session_id = self.session.session_id
        with self.client.settings(strict=False):
            response = self.service.GetPosition(
                SessionId=session_id, DraftShieldIds={"DraftShieldIdentifier": doors}
            )
        self.check_response(response)
        return response["DraftShieldsInformation"]["DraftShieldInformation"]

    def set_door_position(self, door: str, position: int):
        session_id = self.session.session_id
        response = self.service.SetPosition(
            SessionId=session_id,
            DraftShieldsPositions={
                "DraftShieldPosition": [
                    {"DraftShieldId": door, "OpeningWidth": position}
                ]
            },
        )
        self.check_response(response)


class Session:
    def __init__(self, host: str, password: str):
        self.session_client = SessionClient(host=host)
        self.host = host
        self.password = password
        self.session_id = None

        self.clients = []

    def open_session(self):
        self.session_id = self.session_client.open_session(password=self.password)

    def close_session(self):
        self.session_client.close_session(session_id=self.session_id)
        self.session_id = None
        self.clients = []

    def renew_session(self):
        self.close_session()
        self.open_session()

    def __enter__(self):
        if self.session_id is None:
            self.open_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session_id is not None:
            self.close_session()

    def __del__(self):
        if self.session_id is not None:
            self.close_session()

    TypeClient = TypeVar("TypeClient", bound=BaseClient)

    def create_client(self, client_type: Type[TypeClient]) -> TypeClient:
        return client_type(host=self.host, session=self)


class MTAutoBalance:
    def __init__(self, host: str, password: str = "mt"):
        self.host = host
        self.password = password

    def get_session(self) -> Session:
        return Session(host=self.host, password=self.password)

    def open_door(self, door: Literal["LeftOuter", "RightOuter"]):
        with self.get_session() as session:
            draft_shields_client = session.create_client(DraftShieldsClient)
            draft_shields_client.set_door_position(door=door, position=98)

            # check if the door is opened
            position = 0
            start_time = time.time()
            while position < 95 and time.time() - start_time < 10:
                time.sleep(0.1)
                position = draft_shields_client.get_door_position(doors=[f"{door}"])[0][
                    "OpeningWidth"
                ]
            else:
                if position < 95:
                    raise MTAutoBalanceError(
                        f"Failed to open the door within 5 seconds. "
                        f"The door position is {position}."
                    )

    def close_door(self, door: Literal["LeftOuter", "RightOuter"]):
        with self.get_session() as session:
            draft_shields_client = session.create_client(DraftShieldsClient)
            draft_shields_client.set_door_position(door=door, position=0)
            time.sleep(1)

            # check if the door is closed
            position = 100
            start_time = time.time()
            while position > 5 and time.time() - start_time < 10:
                time.sleep(0.1)
                position = draft_shields_client.get_door_position(doors=[f"{door}"])[0][
                    "OpeningWidth"
                ]
            else:
                if position > 5:
                    raise MTAutoBalanceError(
                        f"Failed to close the door within 5 seconds. "
                        f"The door position is {position}."
                    )

    def get_weight(
        self, weight_capture_mode: Literal["Stable", "Immediate"] = "Stable"
    ):
        with self.get_session() as session:
            weighing_client = session.create_client(WeighingClient)
            return weighing_client.get_weight(weight_capture_mode=weight_capture_mode)

    def zero(self):
        with self.get_session() as session:
            weighing_client = session.create_client(WeighingClient)
            weighing_client.zero(zero_immediately=True)

    def automatic_dosing(
        self,
        target_value_g: float,
        lower_tolerance_percent: float,
        upper_tolerance_percent: float,
    ):
        """
        All the possible errors:

            Enumeration DosingLiftBlocked
            Enumeration DosingLiftOverload
            Enumeration NoVialDetected
            Enumeration DosingPositionNotReachable
            Enumeration StaticDetectionFailed
            Enumeration TareNegativeGrossWeight
            Enumeration TareUnderload
            Enumeration TareOverload
            Enumeration TareAborted
            Enumeration TargetWeightPlusTareWeightExceedBalanceCapacity
            Enumeration RfidTagError
            Enumeration HeadCouplingOperationError
            Enumeration PowderTooHard
            Enumeration SubstanceFlowTooLow
            Enumeration DosingUnderload
            Enumeration DosingOverload
            Enumeration DosingError
            Enumeration CaptureWeightNotStable
            Enumeration CaptureWeightOverload
            Enumeration CaptureWeightUnderload
            Enumeration CaptureWeightAlibiError
            Enumeration CaptureWeightAlibiBusy
            Enumeration CaptureWeightFailed
            Enumeration PumpError
            Enumeration PersistingFailed
        """
        with self.get_session() as session:
            dosing_automation_client = session.create_client(DosingAutomationClient)
            notification_client = session.create_client(NotificationClient)
            weighing_task_client = session.create_client(WeightingTaskClient)

            methods = weighing_task_client.get_weighing_methods()
            try:
                method = [
                    method["Name"]
                    for method in methods
                    if method["MethodType"] == "AutomatedDosing"
                ]
                if any(m["Name"] == "Dosing UNSTABLE" for m in methods):
                    method = "Dosing UNSTABLE"
                else:
                    method = method[0]
            except IndexError:
                return {
                    "error": "No AutomatedDosing method found",
                    "result": None,
                    "success": False,
                }

            try:
                weighing_task_client.start_weighing_task(method=method)
            except MTAutoBalanceError as e:
                return {
                    "error": str(e),
                    "result": None,
                    "success": False,
                }

            try:
                dosing_head_info = dosing_automation_client.read_dosing_head()
            except MTAutoBalanceError as e:
                return {
                    "error": str(e),
                    "result": None,
                    "success": False,
                }
            substance_name = dosing_head_info["DosingHeadInfo"]["SubstanceName"]

            # try:
            #     weighing_client.zero(zero_immediately=True)
            # except MTAutoBalanceError as e:
            #     return {
            #         "error": f"Failed to zero the balance. The error message: \n{e}",
            #         "result": None,
            #         "success": False,
            #     }
            try:
                dosing_automation_client.start_dosing(
                    substance_name=substance_name,
                    vial_name="Vial",
                    target_value_g=target_value_g,
                    lower_tolerance_percent=lower_tolerance_percent,
                    upper_tolerance_percent=upper_tolerance_percent,
                )
            except MTAutoBalanceError as e:
                return {
                    "error": f"Failed to start dosing. The error message: \n{e}",
                    "result": None,
                    "success": False,
                }

            time.sleep(1)

            job_start_time = time.time()
            job_finish_time = None

            while True:
                notifications = notification_client.get_notifications()
                if job_finish_time is None and time.time() - job_start_time > 600:
                    return {
                        "error": "The dosing job has not finished within 10 minutes.",
                        "result": None,
                        "success": False,
                    }
                if job_finish_time is not None and time.time() - job_finish_time > 60:
                    return {
                        "error": "Failed to move dosing head back to home within one minute.",
                        "result": result["result"],
                        "success": False,
                    }
                if any(
                    next(iter(notification))
                    == "DosingAutomationActionAsyncNotification"
                    for notification in notifications
                ):
                    notification = [
                        notification
                        for notification in notifications
                        if next(iter(notification))
                        == "DosingAutomationActionAsyncNotification"
                    ][0]["DosingAutomationActionAsyncNotification"]

                    if (
                        notification["DosingJobActionType"] == "PlaceVial"
                        and notification["ActionItem"] == "Vial"
                        and notification["DosingJobActionReason"] == "DosingJobSetup"
                    ):
                        dosing_automation_client.confirm_dosing_job_action(
                            dosing_job_action="PlaceVial",
                            action_item="Vial",
                        )
                    else:
                        return {
                            "error": f"Action required. The action detail:\n{notification}",
                            "result": None,
                            "success": False,
                        }
                if any(
                    next(iter(notification))
                    == "DosingAutomationJobFinishedAsyncNotification"
                    for notification in notifications
                ):
                    notification = [
                        notification
                        for notification in notifications
                        if next(iter(notification))
                        == "DosingAutomationJobFinishedAsyncNotification"
                    ][0]["DosingAutomationJobFinishedAsyncNotification"]
                    job_finish_time = time.time()

                    if notification["DosingError"]:
                        result = {
                            # e.g. SubstanceFlowTooLow
                            "error": notification["DosingError"],
                            "result": notification["DosingResult"]["WeightSample"],
                            "success": False,
                        }
                    else:
                        result = {
                            "error": None,
                            "result": (
                                BalanceWeightResult(
                                    **serialize_object(
                                        notification["DosingResult"]["WeightSample"]
                                    )
                                )
                                if notification["DosingResult"]["WeightSample"]
                                else None
                            ),
                            "success": True,
                        }
                if any(
                    next(iter(notification))
                    == "DosingAutomationFinishedAsyncNotification"
                    for notification in notifications
                ):
                    # indicating the dosing head has been moved back to home
                    return result


if __name__ == "__main__":
    mt_balance = MTAutoBalance(host="http://192.168.1.13:81", password="mt")
    print(
        mt_balance.automatic_dosing(
            target_value_g=0.5, lower_tolerance_percent=0.1, upper_tolerance_percent=0.1
        )
    )
