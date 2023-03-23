#include <Arduino.h>
#include <EtherCard.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>
#include <Servo.h>

#define button1 3  //Start
#define button2 4  //Stop
#define button3 5  //Frequency +
#define button4 6  //Frequency -
#define button5 11 //Open/Close Grabber
#define analogIn 18 //pressure
#define output1 19 //Start
#define output2 20 //Stop
#define output3 21 //Frequency +
#define output4 22 //Frequency -
#define output5 9
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled

#define NIP 192, 168, 0, 32

using namespace ace_routine;

static byte mymac[] = { 0x74, 0x69, 0x30, 0x2F, 0x22, 0x32 };
static byte myip[] = { NIP };

static byte Ethernet::buffer[400];
BufferFiller bfill;
Servo actuator; // create a servo object named "actuator"
bool detect=false;
bool grabberOpenState=true;
bool done=true;
bool start_done=true;
bool stop_done=true;
int stop_counter=0;
bool frequp_done=true;
bool freqdw_done=true;
bool stop_cooldown=false;

int mag=1000,tmp;
unsigned long closeTime, closeTimePrev;
unsigned long startTime, startTimePrev, stopTime, stopTimePrev, frequpTime, frequpTimePrev, freqdwTime, freqdwTimePrev;
unsigned long stopCooldownTime, stopCooldownTimePrev;
const long closeDuration = 400;
const long startDuration = 3000;
const long stopDuration = 4000;
const long stopCooldownDuration = 1000;
const int stopRetry = 2;
const long frequpDuration = 30;
const long freqdwDuration = 30;
String command = "none";

enum State {
  RUNNING,
  STOP
};

int currentFreq = -1;
State state = STOP;

static int getIntArg(const char* data, const char* key, int value =-1) {
    char temp[10];
    if (ether.findKeyVal(data + 7, temp, sizeof temp, key) > 0)
        value = atoi(temp);
    return value;
}

void machineStart(){
  start_done=false;
  startTime=millis();
  startTimePrev=millis();
  Serial.println(F("Machine starts"));
  state=RUNNING;
}

static void machineStart(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  machineStart();
  response["status"] = "success";
  response["currentFreq"] = currentFreq;
  buf.emit_p(PSTR(
  "HTTP/1.0 200 OK\r\n"
  "Content-Type: application/json\r\n"
  "\r\n"));
  serializeJson(response, buf);
}

void machineStop(){
  stop_done=false;
  stopTime=millis();
  stopTimePrev=millis();
  Serial.println(F("Machine stops"));
  state=STOP;
}

static void machineStop(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
    machineStop();
    response["status"] = "success";
    response["currentFreq"] = currentFreq;
    buf.emit_p(PSTR(
      "HTTP/1.0 200 OK\r\n"
      "Content-Type: application/json\r\n"
      "\r\n"));
    serializeJson(response, buf);
}

void frequencyUp(){
  frequp_done=false;
  frequpTime=millis();
  frequpTimePrev=millis();
  currentFreq++;
  Serial.println(F("Frequency +1"));
}

static void frequencyUp(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  frequencyUp();
  response["status"] = "success"; 
  response["currentFreq"] = currentFreq;
  buf.emit_p(PSTR(
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"));
  serializeJson(response, buf);
}

void frequencyDown(){
  freqdw_done=false;
  freqdwTime=millis();
  freqdwTimePrev=millis();
  currentFreq--;
  Serial.println(F("Frequency -1"));
}

static void frequencyDown(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  frequencyDown();
  response["status"] = "success";
  response["currentFreq"] = currentFreq;
  buf.emit_p(PSTR(
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"));
  serializeJson(response, buf);
}

COROUTINE(clicker) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (start_done==false) {
      startTime=millis();
      digitalWrite(output1, HIGH);
      if ((startTime-startTimePrev)>startDuration){
        startTimePrev=startTime;
        start_done=true;
        digitalWrite(output1, LOW);
      }
    }
    if (stop_done==false) {
      stopTime=millis();
      digitalWrite(output2, HIGH);
      if ((stopTime-stopTimePrev)>stopDuration){
        stopTimePrev=stopTime;
        stop_done=true;
        digitalWrite(output2, LOW);
        stop_counter=stop_counter+1;
        if (stop_counter<stopRetry){
          stop_cooldown=true;
          stopCooldownTimePrev=millis();
          stopCooldownTime=millis();
        }
      }
    }
    if (stop_cooldown==true){
      stopCooldownTime=millis();
      digitalWrite(output2, LOW);
      if ((stopCooldownTime-stopCooldownTimePrev)>stopCooldownDuration){
        machineStop();
        stop_cooldown=false;
      }
    }
    if (frequp_done==false) {
      frequpTime=millis();
      digitalWrite(output3, HIGH);
      if ((frequpTime-frequpTimePrev)>frequpDuration){
        frequpTimePrev=frequpTime;
        frequp_done=true;
        digitalWrite(output3, LOW);
      }
    }
    if (freqdw_done==false) {
      freqdwTime=millis();
      digitalWrite(output4, HIGH);
      if ((freqdwTime-freqdwTimePrev)>freqdwDuration){
        freqdwTimePrev=freqdwTime;
        freqdw_done=true;
        digitalWrite(output4, LOW);
      }
    }
  }
}

static void getState(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  response["status"] = "success";
  response["state"] = state == RUNNING ? "RUNNING" : "STOPPED";
  response["grabber"] = grabberOpenState == true ? "Open" : "Close";
  response["detect"] = detect == true ? "1" : "0";
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

void readSensor(){
  tmp=analogRead(analogIn);
  Serial.print("Analog reading:");
  Serial.println(tmp);
  if (tmp<100){
    detect=true;
    Serial.println("detected something");
  }
}

COROUTINE(grabber) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (state == RUNNING && command == "close" && done == false) {
      closeTime=millis();
      if ((closeTime-closeTimePrev)>closeDuration){
        closeTimePrev=closeTime;
        if (mag<=1500 && detect){
          Serial.println("closed properly");
          grabberOpenState=false;
          state=STOP;
          done=true;
        }
        else if (mag<=1500 && !detect){
          mag=mag+50;
          actuator.writeMicroseconds(mag);
          readSensor();
        }
        else if (mag>1500 && !detect){
          Serial.println("closed but program failed to detect");
          grabberOpenState=false;
          state=STOP;
          done=true;
        }
      }
    }
    else if (state == RUNNING && command == "open" && done == false) {
      Serial.println(F("opening."));
      mag=1000;
      actuator.writeMicroseconds(mag);
      COROUTINE_DELAY(3000);
      Serial.println("opened.");
      detect=false;
      grabberOpenState=true;
      done=true;
      state=STOP;
    }
  }
}

void grabberOpen(){
  Serial.print(F("Open function called: "));
  state = RUNNING;
  command = "open";
  done=false;
}

static void grabberOpen(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } 
  else {
  grabberOpen();
  response["status"] = "success";
  response["Open/close function called"] = "success";
  buf.emit_p(PSTR(
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"));
  serializeJson(response, buf);
  }
}

void grabberClose(){
  Serial.print(F("Close function called: "));
  state = RUNNING;
  command = "close";
  done=false;
}

static void grabberClose(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } 
  else {
  grabberClose();
  response["status"] = "success";
  response["Open/close function called"] = "success";
  buf.emit_p(PSTR(
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"));
  serializeJson(response, buf);
  }
}

COROUTINE(handleSerialRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    String text;
    if (Serial.available() != 0) {
        text = Serial.readString();
        if (text == "start"){
          machineStart();
        }
        else if (text == "stop"){
          machineStop();
        }
        else if (text == "freq-up"){
          frequencyUp();
        }
        else if (text == "freq-down"){
          frequencyDown();
        }
        else if (text == "freq"){
          Serial.print(F("Current frequency is: "));
          Serial.println(currentFreq);
        }
        else if (text == "grabber"){
          if (grabberOpenState == true){
            grabberClose();
          }
          else if (grabberOpenState != true){
            grabberOpen();
          }
        }
        else {
          Serial.print(F("Unkown command: "));
          Serial.println(text);
          break;
        }
    }
  }
}

COROUTINE(handleButtonChange) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (digitalRead(button1) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button1) != HIGH);
      machineStart();
    }
    if (digitalRead(button2) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button2) != HIGH);
      machineStop();
      stop_counter=0;
    }
    if (digitalRead(button3) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button3) != HIGH);
      frequencyUp();
    }
    if (digitalRead(button4) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button4) != HIGH);
      frequencyDown();
    }
    if (digitalRead(button5) == HIGH) {
      COROUTINE_AWAIT(digitalRead(button5) != HIGH);
      if (grabberOpenState == true){
        grabberClose();
      }
      else if (grabberOpenState != true){
        grabberOpen();
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

      // receive buf hasn't been clobbered by reply yet
      if (strncmp("GET /start", data, 10) == 0) {
        machineStart(data, bfill);
      }
      else if (strncmp("GET /stop", data, 9) == 0) {
        machineStop(data, bfill);
        stop_counter=0;
      }
      else if (strncmp("GET /freq-up", data, 12) == 0) {
        frequencyUp(data, bfill);
      }
      else if (strncmp("GET /freq-down", data, 14) == 0) {
        frequencyDown(data, bfill);  
      } 
      else if (strncmp("GET /state", data, 10) == 0) {
        getState(data, bfill); 
      } 
      else if (strncmp("GET /grabber-open", data, 17) == 0) {
        grabberOpen(data, bfill); 
      }
      else if (strncmp("GET /grabber-close", data, 18) == 0) {
        grabberClose(data, bfill); 
      }
      else {
        page_404(data, bfill);
      }
      ether.httpServerReply(bfill.position()); // send web page data
    }  
  }
}

//COROUTINE(keepRunning) {
//  COROUTINE_LOOP() {
//    COROUTINE_DELAY(10000);
//    if (state == RUNNING) {
//      machineStart();
//    }
//  }
//}

void setup()
{
  Serial.begin(9600);

//  while (!Serial) ;

  if (ether.begin(sizeof Ethernet::buffer, mymac) == 0)
    Serial.println( "Failed to access Ethernet controller");

  ether.staticSetup(myip);
  Serial.print(F("IP was set to: "));
  for (int i = 0; i < 4; i++) {
    Serial.print(String(myip[i]));
    if (i < 3) {
      Serial.print(".");
    } else {
      Serial.println("");
    }
  }
  actuator.attach(output5); // attach the actuator to Arduino pin output5 (PWM)
    
  pinMode (button1, INPUT);
  pinMode (button2, INPUT);
  pinMode (button3, INPUT);
  pinMode (button4, INPUT);
  pinMode (button5, INPUT);
  pinMode (analogIn, INPUT_PULLUP);
  pinMode (output1, OUTPUT);
  pinMode (output2, OUTPUT);
  pinMode (output3, OUTPUT);
  pinMode (output4, OUTPUT);
  pinMode (output5, OUTPUT);

  digitalWrite(output1, LOW); 
  digitalWrite(output2, LOW); 
  digitalWrite(output3, LOW); 
  digitalWrite(output4, LOW); 
  digitalWrite(output5, LOW);

  // initialize the machine
  // set the frequency to 15 (minimum)
  // stop the machine
  machineStop();
  currentFreq = 15;
  grabberOpenState=true;
  Serial.println(F("Device AutoClicker started."));
  closeTime = millis();
  closeTimePrev = millis();
  startTime = millis();
  startTimePrev = millis();
  stopTime = millis(); 
  stopTimePrev = millis();
  frequpTime = millis();
  frequpTimePrev = millis();
  freqdwTime = millis();
  freqdwTimePrev = millis();
}

void loop()
{
  handleButtonChange.runCoroutine();
  handleSerialRequest.runCoroutine();
  handleRemoteRequest.runCoroutine();
  grabber.runCoroutine();
  clicker.runCoroutine();
}
