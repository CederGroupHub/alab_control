// This is a demo of the RBBB running as webserver with the EtherCard
// 2010-05-28 <jc@wippler.nl>
//
// License: GPLv2

#include <Arduino.h>
#include <EtherCard.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>

#include <Wire.h>
#include <Stepper.h>
#include "SSD1306Ascii.h"
#include "SSD1306AsciiWire.h"

using namespace ace_routine;

#define IRPin1 7 // Have to be interrupt pin
//#define IRPin2 3 // Have to be interrupt pin

#define stepPin1 4
#define stepPin2 6
#define stepPin3 5
#define stepPin4 8

#define button1 A0
#define button2 A1
#define button3 A2

#define STEPS_PER_REV 200

bool statusSensorNow = false;
bool statusSensorPrev = false;
unsigned long dispenseTime, dispenseTimePrev, sphereCountTime, sphereCountTimePrev;
const long dispenseDuration = 500;
const long sphereCountDuration = 500;

#define I2C_ADDRESS 0x3C
#define RST_PIN -1
SSD1306AsciiWire oled;

Stepper stepMot(STEPS_PER_REV, stepPin1, stepPin2, stepPin3, stepPin4);

enum State {
  RUNNING,
  STOP
};

// ethernet interface mac address, must be unique on the LAN
static byte mymac[] = { 0x74,0x39,0x70,0x2D,0x30,0x31 };
static byte myip[] = { 192,168,0,33};
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
  writeDisplay(1);
}

inline void stop_work() {
  restBallNumber = 0;
  state = STOP;
  writeDisplay(1);
}

inline void change_number(int n) {
  if (n > 0 && n <= 100) {
    ballNumber = n;
    writeDisplay(1);
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
    writeDisplay(1);
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
    writeDisplay(1);
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


void writeDisplay(int mode) {
  switch (mode) {
    case 1: //default screen update
      oled.clear();
      oled.set1X();
      if (state == STOP) {
        // first row
        oled.println(F("A-LAB SPHERE DISPENSER"));
  
        // second row
        oled.print("Amount:  ");
        oled.set2X();
        oled.println(ballNumber);
        // third row
        oled.set1X();
        oled.print(F("Press GO to dispense"));
      } else {
        // first row
        oled.println(F(">> Dispenser RUNNING"));
  
        // second row
        oled.print(F("Done/Tot  "));
        oled.set2X();
        oled.print(ballNumber - restBallNumber);
        oled.print("/");
        oled.println(ballNumber);
        oled.set1X();
        oled.print(F("Press GO to stop"));
      }
      break;
      
    default: //initial screen
      oled.clear();
      // first row
      oled.println(F("     >> A-LAB <<"));
      oled.println(F(""));
      oled.println(F("       SPHERE"));
      oled.println(F("      DISPENSER"));
      delay(2000);
      break;
  }
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

      if (restBallNumber > 0){
        writeDisplay(1);
      }
      
    } else {
      COROUTINE_DELAY(100);
    }
    if (restBallNumber <= 0 and state == RUNNING) {
      state = STOP;
      Serial.print(F("Dispensed "));
      Serial.print(ballNumber-restBallNumber);
      Serial.println(F(" spheres."));
      writeDisplay(1);
    }
  }
}

COROUTINE(handleSerialRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    String text;

    if (Serial.available() != 0) {
      //Serial.println(Serial.read());
      //reqSpheres = Serial.parseInt(); //Read the data the user has input
      text = Serial.readString();
      int reqSpheres = text.toInt();
      Serial.print(F("Received serial command. Dispensing "));
      Serial.print(reqSpheres);
      Serial.println(F(" spheres."));
      change_number(reqSpheres);
      start_work();
    }
  }
}

COROUTINE(handleButtonChange) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
      if (digitalRead(button1) == HIGH) {
        COROUTINE_AWAIT(digitalRead(button1) != HIGH);
        if (ballNumber < 100) {
          change_number(ballNumber + 1);
          Serial.print(F("Added one. Now you have "));
          Serial.print(ballNumber);
          Serial.println(F(" spheres to go."));
        }
    }
  
    if (digitalRead(button2) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button2) != HIGH);
      if (ballNumber > 0) {
        change_number(ballNumber - 1);
        Serial.print(F("Removed one. Now you have "));
        Serial.print(ballNumber);
        Serial.println(F(" spheres to go."));
      }
    }
  
    if (digitalRead(button3) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button3) == HIGH);
      if (state == STOP) {
        Serial.print(F("GO button pressed. Dispensing "));
        Serial.print(ballNumber);
        Serial.println(F(" now."));
        start_work();
      } else {
        Serial.print(F("Receive stop signal. We need "));
        Serial.print(restBallNumber);
        Serial.println(F(" more balls."));
        stop_work();
      }
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
  Wire.begin();
  oled.begin(&Adafruit128x32, I2C_ADDRESS);
  oled.setFont(Adafruit5x7);
  writeDisplay(0);
  Serial.begin(9600);
  if (ether.begin(sizeof Ethernet::buffer, mymac, SS) == 0){
    Serial.println(F("Failed to access Ethernet controller"));
  }
  ether.dhcpSetup();

  attachInterrupt(digitalPinToInterrupt(IRPin1), addSphereCount, RISING);
//  attachInterrupt(digitalPinToInterrupt(IRPin2), addSphereCount, RISING);
//  pinMode (button1, INPUT);
//  pinMode (button2, INPUT);
//  pinMode (button3, INPUT);
  pinMode(stepPin1, OUTPUT);
  pinMode(stepPin2, OUTPUT);
  pinMode(stepPin3, OUTPUT);
  pinMode(stepPin4, OUTPUT);
  
  digitalWrite(stepPin1, LOW);
  digitalWrite(stepPin2, LOW);
  digitalWrite(stepPin3, LOW);
  digitalWrite(stepPin4, LOW);

  Serial.println(F("Type the number of spheres you want"));
  writeDisplay(1);
  
  dispenseTime = millis();
  dispenseTimePrev = millis();

  sphereCountTime = millis();
  sphereCountTimePrev = millis();
}

void loop () {
  dispenseBalls.runCoroutine();
//  handleButtonChange.runCoroutine();
  handleSerialRequest.runCoroutine();
  handleRemoteRequest.runCoroutine();
}
