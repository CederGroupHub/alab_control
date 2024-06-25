import abc
from pathlib import Path
from typing import Literal, Type, TypeVar

import zeep

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


class MTAutoBalanceError(Exception):
    pass


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
    ) -> dict:
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
        return response["WeightSample"]

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


class DosingAutomationClient(BaseClient):
    name = "DosingAutomationService"

    def read_dosing_head(self) -> dict:
        """
        Get information about the dosing head.

        Example:
        {
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
            'NumberOfDosages': 2,
            'RemainingDosages': 248
        }
        """
        session_id = self.session.session_id
        with self.client.settings(
            strict=False
        ):  # the response is not strictly following the schema
            response = self.service.ReadDosingHead(SessionId=session_id)
        self.check_response(response)
        return response["DosingHead"]

    def start_dosing(
        self,
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
                        "SubstanceName": "??",
                        "VialName": "vial",
                        "TargetWeight": {
                            "Value": target_value_g,
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


if __name__ == "__main__":
    with Session(host="http://192.168.1.10:81", password="mt") as session:
        dosing_automation_client = session.create_client(DosingAutomationClient)
        dosing_automation_client.start_dosing(
            target_value_g=1, lower_tolerance_percent=0.1, upper_tolerance_percent=0.1
        )
