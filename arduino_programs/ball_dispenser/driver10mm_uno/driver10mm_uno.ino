// This is a demo of the RBBB running as webserver with the EtherCard
// 2010-05-28 <jc@wippler.nl>
//
// License: GPLv2

#include <Arduino.h>
#include <EtherCard.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>

#include <Stepper.h>
using namespace ace_routine;

#define IRPin1 2 // Have to be interrupt pin

#define stepPin1 4
#define stepPin2 5
#define stepPin3 8
#define stepPin4 6

#define STEPS_PER_REV 200

bool statusSensorNow = false;
bool statusSensorPrev = false;
unsigned long dispenseTime, dispenseTimePrev, sphereCountTime, sphereCountTimePrev;
const long dispenseDuration = 500;
const long sphereCountDuration = 500;

Stepper stepMot(STEPS_PER_REV, stepPin1, stepPin4, stepPin2, stepPin3);

enum State {
  RUNNING,
  STOP
};

// ethernet interface mac address, must be unique on the LAN
static byte mymac[] = { 0x74,0x39,0x70,0x2D,0x30,0x35 };
State state = STOP;
int ballNumber = 1;
int restBallNumber = 0;
bool detected = false;

static byte Ethernet::buffer[400];                      
BufferFiller bfill;

static int getIntArg(const char* data, const char* key, int value =-1) {
    char temp[10];
    if (ether.findKeyVal(data + 7, temp, sizeof temp, key) > 0)
        value = atoi(temp);
    return value;
}

inline void start_work() {
  state = RUNNING;
  restBallNumber = ballNumber;
}

inline void stop_work() {
  restBallNumber = 0;
  state = STOP;
}

inline void change_number(int n) {
  if (n > 0 && n <= 100) {
    ballNumber = n;
  }
}

static void start_work(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    start_work();
    response["status"] = "success";
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void stop_work(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != RUNNING) {
    response["status"] = "error";
    response["reason"] = "The machine is not running.";
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    response["status"] = "success";
    response["rest_ball_number"] = restBallNumber;
    stop_work();
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void change_number(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  int n = getIntArg(data, "n");
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = "The machine is still running.";
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else if (n == -1) {
    response["status"] = "error";
    response["reason"] = "Missing ball number.";
    buf.emit_p(PSTR(
        "HTTP/1.0 400 Bad Request\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  } else if (n < 0 || n > 100) {
    response["status"] = "error";
    response["reason"] = "Unexpected ball number. Expected ball number range: 1~100.";
    buf.emit_p(PSTR(
        "HTTP/1.0 400 Bad Request\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  } else {
    delay(1);
    change_number(n);
    response["status"] = "success";
    response["number"] = n;
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void get_number(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  response["status"] = "success";
  response["number"] = ballNumber;
  buf.emit_p(PSTR(
      "HTTP/1.0 200 OK\r\n"
      "Content-Type: application/json\r\n"
      "\r\n"));
  serializeJson(response, buf);
}

static void page_404(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  response["status"] = "error";
  response["reason"] = "Requested endpoint not found.";
  bfill.emit_p(PSTR(
      "HTTP/1.0 404 Not Found\r\n"
      "Content-Type: application/json\r\n"
      "\r\n"));
   serializeJson(response, buf);
}

static void getState(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  response["status"] = "success";
  response["state"] = state == RUNNING ? "RUNNING" : "STOPPED";
  buf.emit_p(PSTR(
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"));
  serializeJson(response, buf);
}

void dispense(Stepper myStepper,int stepperSpeed, int percent=25){
  if (stepperSpeed > 0) {
    myStepper.setSpeed(stepperSpeed);
    // step n/100 of a revolution:
    myStepper.step(-percent*STEPS_PER_REV/100);
  }
  digitalWrite(stepPin1, LOW);
  digitalWrite(stepPin2, LOW);
  digitalWrite(stepPin3, LOW);
  digitalWrite(stepPin4, LOW);
}

void addSphereCount(){
  sphereCountTime=millis();
  if ((sphereCountTime-sphereCountTimePrev)>sphereCountDuration){
    sphereCountTimePrev=sphereCountTime;
    restBallNumber--;
    Serial.print("+1 ");
    Serial.println("Dispensed one.");
    Serial.println(F(""));
    Serial.print(restBallNumber);
    Serial.println(F(" remaining."));
  }
  else{
  }
}

COROUTINE(dispenseBalls) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (state == RUNNING && restBallNumber > 0) {
      dispenseTime=millis();
      if((dispenseTime-dispenseTimePrev) > dispenseDuration){
        dispenseTimePrev=dispenseTime;
        dispense(stepMot, 30, 5);
      }
      
    } 
    else {
      COROUTINE_DELAY(100);
    }
    if (restBallNumber <= 0 and state == RUNNING) {
      state = STOP;
      Serial.print(F("Dispensed "));
      Serial.print(ballNumber-restBallNumber);
      Serial.println(F(" spheres."));
    }
  }
}

COROUTINE(handleRemoteRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    word len = ether.packetReceive();
    word pos = ether.packetLoop(len);
  
    if (pos) {
      bfill = ether.tcpOffset();
      char* data = (char *) Ethernet::buffer + pos;
  //    Serial.println(data);
      // receive buf hasn't been clobbered by reply yet
      if (strncmp("GET /start", data, 10) == 0) {
        start_work(data, bfill);
      }
      else if (strncmp("GET /stop", data, 9) == 0) {
        stop_work(data, bfill);
      }
      else if (strncmp("GET /change", data, 11) == 0) {
        change_number(data, bfill);
      }
      else if (strncmp("GET /num", data, 8) == 0) {
        get_number(data, bfill);  
      }
      else if (strncmp("GET /state", data, 10) == 0) {
        getState(data, bfill);
      }
      else {
        page_404(data, bfill);
      }
      ether.httpServerReply(bfill.position()); // send web page data
    }  
  }  
}

void setup () {
  delay(1000);
  Serial.begin(9600);
  Serial.println("Try to connect..");
  if (ether.begin(sizeof Ethernet::buffer, mymac, SS) == 0){
    Serial.println(F("Failed to access Ethernet controller"));
  }
  ether.dhcpSetup();
  Serial.println("Connected!");

  attachInterrupt(digitalPinToInterrupt(IRPin1), addSphereCount, RISING);
  pinMode(stepPin1, OUTPUT);
  pinMode(stepPin2, OUTPUT);
  pinMode(stepPin3, OUTPUT);
  pinMode(stepPin4, OUTPUT);
  
  digitalWrite(stepPin1, LOW);
  digitalWrite(stepPin2, LOW);
  digitalWrite(stepPin3, LOW);
  digitalWrite(stepPin4, LOW);

  Serial.println(F("Type the number of spheres you want"));
  
  dispenseTime = millis();
  dispenseTimePrev = millis();

  sphereCountTime = millis();
  sphereCountTimePrev = millis();
}

void loop () {
  dispenseBalls.runCoroutine();
  handleRemoteRequest.runCoroutine();
}
