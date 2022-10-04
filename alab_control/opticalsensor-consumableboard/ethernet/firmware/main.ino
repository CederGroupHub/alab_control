#include <Arduino.h>
#include <EtherCard.h>
#include <ArduinoJson.h>
#include <AceRoutine.h>
#include <config.h> // holds the board config values (pins, thresholds, etc)
/***     Setup      ***/
// multiplexing
bool isOn[numSourcePins][numReadPins]; // 2d array of booleans that represent the state of each phototransistor. true = on, false = off.

// ethernet
static byte Ethernet::buffer[200];
BufferFiller bfill;

static int getIntArg(const char *data, const char *key, int value = -1)
{
    char temp[10];
    if (ether.findKeyVal(data + 7, temp, sizeof temp, key) > 0)
        value = atoi(temp);
    return value;
}

static void page_404(const char *data, BufferFiller &buf)
{
    // returns a 404 response to unknown requests
    DynamicJsonDocument response(256);
    response["status"] = "error";
    response["reason"] = "Requested endpoint not found.";
    bfill.emit_p(PSTR(
        "HTTP/1.0 404 Not Found\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
}

static void page_state(const char *data, BufferFiller &buf)
{
    // returns the filled state of the board (true/false) for each phototransistor. given in 2d array format
    DynamicJsonDocument response(256);
    response["status"] = "success";

    JsonArray filled = response.createNestedArray("filled");
    for (int row = 0; row < numSourcePins; row++)
    {
        JsonArray rowArray = filled.createNestedArray();
        for (int col = 0; col < numReadPins; col++)
        {
            rowArray.add(isOn[row][col]);
        }
    }

    bfill.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
    serializeJson(response, buf);
}

/*** Methods ***/

COROUTINE(scanGrid)
{
    COROUTINE_LOOP()
    {
        for (int row = 0; row < numSourcePins; row++)
        {
            digitalWrite(sourcePins[row], HIGH);
            for (int col = 0; col < numReadPins; j++)
            {
                int val = analogRead(readPins[col]);
                isOn[row][col] = val > ON_THRESHOLD;
                // bool newState = val > ON_THRESHOLD;
                // if (newState != isOn[row][col])
                // {
                //     isOn[row][col] = newState;
                //     send_state(row * numReadPins + col);
                // }
            }
            digitalWrite(sourcePins[i], LOW);
            COROUTINE_DELAY(30); // wait 30ms between scanning each row
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
            //    Serial.println(data);
            // receive buf hasn't been clobbered by reply yet
            if (strncmp("GET /state", data, 10) == 0)
            {
                page_state(data, bfill);
            }
            else
            {
                page_404(data, bfill);
            }
            ether.httpServerReply(bfill.position()); // send web page data
        }
    }
}

/*** Runtime ***/
void setup()
{
    // initialize serial communication at 9600 bits per second:
    Serial.begin(BAUDRATE);
    if (ether.begin(sizeof Ethernet::buffer, mymac, SS) == 0)
    {
        Serial.println(F("Failed to access Ethernet controller"));
    }
    ether.staticSetup(myip);

    // intialize the multiplexing grid
    for (int i = 0; i < numSources; i++)
    {
        pinMode(sourcePins[i], OUTPUT);
        digitalWrite(sourcePins[i], LOW);
    }
    for (int i = 0; i < numReads; i++)
    {
        pinMode(readPins[i], INPUT);
    }
}
void loop()
{
    scanGrid.runCoroutine();
    handleRemoteRequest.runCoroutine();
}
