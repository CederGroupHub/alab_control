#include <Servo.h>
#include <EtherCard.h>
#include <ArduinoJson.h>
#include <AceRoutine.h>

#define NIP 192, 168, 0, 51

using namespace ace_routine;

static byte mymac[] = {0x74, 0x69, 0x30, 0x2F, 0x22, 0x2f};
static byte myip[] = {NIP};

static byte Ethernet::buffer[200];
BufferFiller bfill;
Servo actuator; // create a servo object named "actuator"

enum State {
  RUNNING,
  STOP
};

const int OPEN = 1300;
const int CLOSE = 1550;

// state variables for totally independent communication and capper actuator coroutines
String command="none";
unsigned long actuateTime, actuateTimePrev;
const long actuateDuration = 2000;
bool done=true;
bool rec_time=false;

State state = STOP;

void setup()
{
  actuator.attach(9);                // attach the actuator to Arduino pin 9 (PWM)
  actuator.writeMicroseconds(OPEN); // give the actuator a 1ms pulse to extend the arm (1000us = 1ms)
  delay(1000);                       // delay a few seconds to give the arm time to retract
  Serial.begin(9600);

  if (ether.begin(sizeof Ethernet::buffer, mymac) == 0)
    Serial.println("Failed to access Ethernet controller");

  ether.staticSetup(myip);
  Serial.print(F("IP was set to: "));
  for (int i = 0; i < 4; i++)
  {
    Serial.print(String(myip[i]));
    if (i < 3)
    {
      Serial.print(".");
    }
    else
    {
      Serial.println("");
    }
  }
}

static int getIntArg(const char *data, const char *key, int value = -1)
{
  char temp[10];
  if (ether.findKeyVal(data + 7, temp, sizeof temp, key) > 0)
    value = atoi(temp);
  return value;
}

void open_capper()
{
  Serial.println("OPENING");
  state = RUNNING;
  command = "open";
  done = false;
  rec_time = true;
}

void close_capper()
{
  Serial.println("CLOSING");
  state = RUNNING;
  command = "close";
  done = false;
  rec_time = true;
}

static void close_capper(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    close_capper();
    response["status"] = "success, closing capper";
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void open_capper(const char* data, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  if (state != STOP) {
    response["status"] = "error";
    response["reason"] = F("The machine is running.");
    buf.emit_p(PSTR(
            "HTTP/1.0 400 Bad Request\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"));
  } else {
    open_capper();
    response["status"] = "success, opening capper";
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

static void get_state(const char *data, BufferFiller &buf)
{
  DynamicJsonDocument response(256);
  response["status"] = "success";
  response["state"] = state == RUNNING ? "RUNNING" : "STOPPED";
  buf.emit_p(PSTR(
      "HTTP/1.0 200 OK\r\n"
      "Content-Type: application/json\r\n"
      "\r\n"));
  serializeJson(response, buf);
}

static void page_404(const char *data, BufferFiller &buf)
{
  DynamicJsonDocument response(256);
  response["status"] = "error";
  response["reason"] = "Requested endpoint not found.";
  bfill.emit_p(PSTR(
      "HTTP/1.0 404 Not Found\r\n"
      "Content-Type: application/json\r\n"
      "\r\n"));
  serializeJson(response, buf);
}

COROUTINE(handleSerialRequest)
{
  COROUTINE_LOOP()
  {
    COROUTINE_DELAY(30);
    String text = "";

    if (Serial.available() != 0)
    {
      text = Serial.readString();

      if (text == "1\n")
      {
        open_capper();
      }
      else if (text == "0\n")
      {
        close_capper();
      }
      else
      {
        Serial.println("Invalid command");
      }
    }
  }
}

COROUTINE(handleRemoteRequest)
{
  COROUTINE_LOOP()
  {
    COROUTINE_DELAY(30);
    word len = ether.packetReceive();
    word pos = ether.packetLoop(len);

    if (pos)
    {
      bfill = ether.tcpOffset();
      char *data = (char *)Ethernet::buffer + pos;

      // receive buf hasn't been clobbered by reply yet
      if (strncmp("GET /open", data, 9) == 0)
      {
        open_capper(data, bfill);
      }
      else if (strncmp("GET /close", data, 10) == 0)
      {
        close_capper(data, bfill);
      }
      else if (strncmp("GET /state", data, 10) == 0)
      {
        get_state(data, bfill);
      }
      else
      {
        page_404(data, bfill);
      }
      ether.httpServerReply(bfill.position()); // send web page data
    }
  }
}

COROUTINE(capper) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (state == RUNNING && command == "open" && done == false) {
      if (rec_time==true){
        actuateTimePrev=millis();
      }
      if (rec_time==true){
        rec_time=false;
        actuator.writeMicroseconds(OPEN);
      }
      actuateTime=millis();
      if ((actuateTime-actuateTimePrev)>actuateDuration){
        done=true;
      }
    }
    else if (state == RUNNING && command == "close" && done == false) {
      if (rec_time==true){
        actuateTimePrev=millis();
      }
      if (rec_time==true){
        rec_time=false;
        actuator.writeMicroseconds(CLOSE);
      }
      actuateTime=millis();
      if ((actuateTime-actuateTimePrev)>actuateDuration){
        done=true;
      }
    }
    else {
      COROUTINE_DELAY(100);
    }
    if (state == RUNNING && done == true) {
      state = STOP;
      Serial.println("Command " + command + " capper successfully done.");
      command = "none";
    }
  }
}

void loop()
{
  capper.runCoroutine();
  handleSerialRequest.runCoroutine();
  handleRemoteRequest.runCoroutine();
}
