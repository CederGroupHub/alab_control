#include <Servo.h>
#include <EtherCard.h>
#include <ArduinoJson.h>
#include <AceRoutine.h>
#include <Servo.h>

#define NIP 192, 168, 0, 51

using namespace ace_routine;

static byte mymac[] = {0x74, 0x69, 0x30, 0x2F, 0x22, 0x2f};
static byte myip[] = {NIP};

static byte Ethernet::buffer[200];
BufferFiller bfill;
Servo actuator; // create a servo object named "actuator"

enum State
{
  OPEN_,
  CLOSE_
};

const int OPEN = 1300;
const int CLOSE = 1550;

State state = OPEN_;

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

void open()
{
  Serial.println("OPENING");
  actuator.writeMicroseconds(OPEN); // give the actuator a 1ms pulse to extend the arm (1000us = 1ms)
  state = OPEN_;
  delay(1000);
}

void close()
{
  Serial.println("CLOSING");
  actuator.writeMicroseconds(CLOSE); // give the actuator a 1ms pulse to extend the arm (1000us = 1ms)
  state = CLOSE_;
  delay(1000);
}

static void close(const char *data, BufferFiller &buf)
{
  DynamicJsonDocument response(256);
  if (state != OPEN_)
  {
    response["status"] = "success";
    response["reason"] = F("The capper is already closed.");
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
  }
  else
  {
    close();
    response["status"] = "success";
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
  }
}

static void open(const char *data, BufferFiller &buf)
{
  DynamicJsonDocument response(256);
  if (state != CLOSE_)
  {
    response["status"] = "success";
    response["reason"] = F("The capper is already open.");
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
  }
  else
  {
    open();
    response["status"] = "success";
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
  }
}

static void get_state(const char *data, BufferFiller &buf)
{
  DynamicJsonDocument response(256);
  response["status"] = "success";
  response["state"] = state == OPEN_ ? "open" : "close";
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
        open();
      }
      else if (text == "0\n")
      {
        close();
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
        open(data, bfill);
      }
      else if (strncmp("GET /close", data, 10) == 0)
      {
        close(data, bfill);
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

void loop()
{
  handleSerialRequest.runCoroutine();
  handleRemoteRequest.runCoroutine();
}
