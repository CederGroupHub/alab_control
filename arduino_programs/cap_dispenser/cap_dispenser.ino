// This is a demo of the RBBB running as webserver with the EtherCard
// 2010-05-28 <jc@wippler.nl>
//
// License: GPLv2

#include <Arduino.h>
#include <EtherCard.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>
#include <Servo.h>

using namespace ace_routine;

#define linacPin1 3
#define linacPin2 5
#define linacPin3 6
#define linacPin4 9

const int linac1open=1800, linac1close=1050;
const int linac2open=1800, linac2close=1050;
const int linac3open=1800, linac3close=1050;
const int linac4open=1800, linac4close=1050;

int linac1mag=linac1close;
int linac2mag=linac2close;
int linac3mag=linac3close;
int linac4mag=linac4close;

unsigned long dispenseTime, dispenseTimePrev;
const long dispenseDuration = 6000;

Servo linac1;
Servo linac2;
Servo linac3;
Servo linac4;

enum State {
  RUNNING,
  STOP
};

// ethernet interface mac address, must be unique on the LAN
static byte mymac[] = { 0x74,0x22,0x69,0x2D,0x30,0x32 };
static byte myip[] = { 192,168,0,31};
State state = STOP;

static byte Ethernet::buffer[400];                      
BufferFiller bfill;

int capNumber=0;
String command="none";
bool done=true;
bool rec_time=false;

static int getIntArg(const char* data, const char* key, int value =-1) {
    char temp[10];
    if (ether.findKeyVal(data + 7, temp, sizeof temp, key) > 0)
        value = atoi(temp);
    return value;
}

inline void open_dispenser(int n) {
  state = RUNNING;
  capNumber = n;
  command = "open";
  done = false;
  rec_time = true;
}

inline void close_dispenser(int n) {
  state = RUNNING;
  capNumber = n;
  command = "close";
  done = false;
  rec_time = true;
}

inline void stop_work() {
  state = STOP;
  command = "none";
}

static void open_dispenser(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  int n = getIntArg(data, "n");
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    open_dispenser(n);
    response["status"] = "success, opening dispenser "+String(n);
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void close_dispenser(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  int n = getIntArg(data, "n");
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    close_dispenser(n);
    response["status"] = "success, closing dispenser "+String(n);
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
    response["status"] = "success, stopping work";
    response["cap_number"] = String(capNumber);
    stop_work();
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
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

COROUTINE(dispenser) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (state == RUNNING && command == "open" && done == false) {
      if (rec_time==true){
        dispenseTimePrev=millis();
      }
      if (capNumber==1 && rec_time==true){
        rec_time=false;
        linac1.writeMicroseconds(linac1open);
      }
      if (capNumber==2 && rec_time==true){
        rec_time=false;
        linac2.writeMicroseconds(linac2open);
      }
      if (capNumber==3 && rec_time==true){
        rec_time=false;
        linac3.writeMicroseconds(linac3open);
      }
      if (capNumber==4 && rec_time==true){
        rec_time=false;
        linac4.writeMicroseconds(linac4open);
      }
      dispenseTime=millis();
      if ((dispenseTime-dispenseTimePrev)>dispenseDuration){
        done=true;
      }
    }
    else if (state == RUNNING && command == "close" && done == false) {
      if (rec_time==true){
        dispenseTimePrev=millis();
      }
      if (capNumber==1 && rec_time==true){
        rec_time=false;
        linac1.writeMicroseconds(linac1close);
      }
      if (capNumber==2 && rec_time==true){
        rec_time=false;
        linac2.writeMicroseconds(linac2close);
      }
      if (capNumber==3 && rec_time==true){
        rec_time=false;
        linac3.writeMicroseconds(linac3close);
      }
      if (capNumber==4 && rec_time==true){
        rec_time=false;
        linac4.writeMicroseconds(linac4close);
      }
      dispenseTime=millis();
      if ((dispenseTime-dispenseTimePrev)>dispenseDuration){
        done=true;
      }
    }
    else {
      COROUTINE_DELAY(100);
    }
    if (state == RUNNING && done == true) {
      state = STOP;
      Serial.println("Command " + command + " dispenser " + String(capNumber) + " successfully done.");
      command = "none";
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
      if (strncmp("GET /open", data, 9) == 0) {
        open_dispenser(data, bfill);
      }
      else if (strncmp("GET /close", data, 10) == 0) {
        close_dispenser(data, bfill);
      }
      else if (strncmp("GET /stop", data, 9) == 0) {
        stop_work(data, bfill);
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
  if (ether.begin(sizeof Ethernet::buffer, mymac, SS) == 0){
    Serial.println(F("Failed to access Ethernet controller"));
  }
  ether.dhcpSetup();
  linac1.attach(linacPin1);
  linac1.writeMicroseconds(linac1close);
  linac2.attach(linacPin2);
  linac2.writeMicroseconds(linac2close); 
  linac3.attach(linacPin3);
  linac3.writeMicroseconds(linac3close); 
  linac4.attach(linacPin4);
  linac4.writeMicroseconds(linac4close); 
  pinMode(linacPin1, OUTPUT);
  pinMode(linacPin2, OUTPUT);
  pinMode(linacPin3, OUTPUT);
  pinMode(linacPin4, OUTPUT);
  dispenseTime = millis();
  dispenseTimePrev = millis();
}

void loop () {
  dispenser.runCoroutine();
  handleRemoteRequest.runCoroutine();
}
