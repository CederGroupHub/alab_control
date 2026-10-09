
/* IMPORTANT NOTES
  This code controls a control panel made for the SEM and TEM auto preparation device. This auto-prep system is, briefly, composed of a computer,
  a control panel and a modified 3D printer. This software controls some of the needed hardware, in conjunction of the actions performed by the
  3D printer. The logic for a proper usage happens inside the computer, not the control panel. Safety procedures are performed by proper training,
  proper installation of the emergency buttons, and safety measures. This embedded software DOES NOT evaluate anything regarding safety and is
  completely blind to what happens in the real world, there are no feedback sensors of any kind.

  /* DEVELOPMENT NOTES
  1. This code does not evaluate if the proper equipment is on before performing tasks that would need them on. This must be corrected.
  2. There is no evaluation on commands order to check if changing states at that moment is allowed (but I think it should be that way).

  /* NOT SO IMPORTANT NOTES
  1. David finished REV01 version in 5 days. 8-)


  END */


/*** INCLUDES AND VARIABLE DECLARATIONS
  *********************************************************************************************************************************/

#include <P1AM.h>
#include <SPI.h>
#include <Ethernet.h>
#include <Servo.h>

//const char P1_04PWM_CONFIG[] = { 0x02, 0x02, 0x02, 0x02 }; //commented to see if this line is necessary. It seems the PWM module was removed

String clientmsg = "";
bool parseerror = false;

Servo linAct;     // P1 : Pin 8
#define linActPin 1
Servo gridLid;     // P2 : Pin 9
#define gridLidPin 2
Servo rotator;     // P3 : Pin 10
#define rotatorPin 3
Servo gripper;    // P4 : Pin 11
#define gripperPin 4

unsigned long servosPoweredTime = 0;
//bool servosPowered = false;
//bool servosAttached = false;
unsigned long procedurestarttime = 0;
int ethernetAttempts = 0;
bool debug = false; // turn this on to bypass the lack of connections to the emergency buttons

/*** MACHINE STATE DECLARATION
*********************************************************************************************************************************

***/

enum panelstate {
  SHUTDWN,  //Everything is OFF/unpowered
  STANDBY,  //Panel resting state, 3D printer and HVPS are ON. If any motor is active, or lid open, or rotation is true, etc - everything goes to zero
  PHLIDMV,  //Phenom Stub Holder Lid Movement - Activates the Linear Actuator to move the lid
  TEMPREP,  //TEM Sample Prep - Vacuum activation, TEM Grid Lid opening, TEM Grid Lid closing
  SEMPREP,  //SEM Sample Prep - Vacuum activation, Stub rotation (true), Stub rotation (false)
  EXPOSUR,  //Sample Exposing - Vibration motors control, HVPS control
  TEMSTOR,  //TEM grid storage - Vacuum deactivation, TEM Grid Lid closing
  SEMSTOR,  //SEM stub storage - Gripper activation, Gripper Deactivation
};

#define IDNAME(name) #name
const char* stateNames[] = { IDNAME(SHUTDWN),
                             IDNAME(STANDBY),
                             IDNAME(PHLIDMV),
                             IDNAME(TEMPREP),
                             IDNAME(SEMPREP),
                             IDNAME(EXPOSUR),
                             IDNAME(TEMSTOR),
                             IDNAME(SEMSTOR)
                           };

panelstate currentState = SHUTDWN;

/*** PANEL "PINOUT" (VARIABLES THAT SAVE EQUIPMENT STATE, SETTINGS, INFO, ETC)
*********************************************************************************************************************************/

//inputs
uint32_t photointerrutor = 0;
bool emergency_stop = false;
#define pingPin 0

//boolean outputs
bool phenomlid_linact = false;
bool phenomlid_linact_action = false;
bool temgrid_servo = false;
bool temgrid_servo_action = false;
bool semrot_servo = false;
bool semrot_servo_action = false;
bool gripper_servo = false;
bool gripper_servo_action = false;
bool hvps_prepare = false;
bool hvps_trigger = false;
bool hvps_trigger_action = false;
bool vacpump_one = false;
bool vacpump_two = false;
bool vibmotor_one = false;
bool vibmotor_two = false;
bool hvps_power = false;
bool printer_power = false;

//integer outputs
int hvps_voltage = 0;
int hvps_exptime = 0;
int phenomlid_linact_ext = 0;
int temgrid_servo_ext = 0;
int semrot_servo_ext = 0;
int gripper_servo_ext = 0;
int phenomlid_linact_ext_home = 150;
int temgrid_servo_ext_home = 158;
int semrot_servo_ext_home = 20;
int gripper_servo_ext_home = 0;
//#define PWM_FREQUENCY 50
//#define TEM_ZERO_POS 0  //this number should be checked
//#define SEM_ZERO_POS 0  //this number should be checked

String output_message = "";

unsigned long gripper_endtime = 0;
long duration = 0;

// Gripper precise movement control variables
int currentGripperPosition = 0;
int targetGripperPosition = 0;
unsigned long lastGripperMoveTime = 0;
bool gripperMoving = false;
const int GRIPPER_THRESHOLD = 80;  // Threshold at position 80
const int GRIPPER_FAST_DELAY = 10; // Faster when below threshold (more open)
const int GRIPPER_SLOW_DELAY = 75; // Slower when above threshold (more closed)
const int GRIPPER_STEP_SIZE = 2;

// TEM Grid lid precise movement control variables
int currentGridLidPosition = 0;
int targetGridLidPosition = 0;
unsigned long lastGridLidMoveTime = 0;
bool gridLidMoving = false;
const int GRID_LID_THRESHOLD = 146;
const int GRID_LID_FAST_DELAY = 10;
const int GRID_LID_SLOW_DELAY = 75;
const int GRID_LID_STEP_SIZE = 2;

/*** ETHERNET AND SERVER CONFIGURATION
*********************************************************************************************************************************/

// Enter a MAC address and IP address for your controller below.
// The IP address will be dependent on your local network:
byte mac[] = {
  0x60, 0x92, 0xE2, 0x1D, 0x22, 0x3A
};
//IPAddress ip(192, 168, 1, 46);

// Initialize the Ethernet client library
// with the IP address and port of the server
// that you want to connect to (port 23 is default for telnet;
// if you're using Processing's ChatServer, use port 10002):
EthernetServer server(8888);

void setup() {

  /*** SERIAL INITIALISATION
  *********************************************************************************************************************************/

  Serial.begin(9600);
  unsigned long startTime = millis();
  while (!Serial) {
    // Check if timeout has occurred
    if (millis() - startTime >= 5000) {
      break;
    }
  }

  Serial.print(F("Serial started! Now starting up Arduino PLC modules..."));

  /*** WATCHDOG PARAMETERS AND INITIALISATION
  *********************************************************************************************************************************/

  P1.configWD(10000, TOGGLE);
  P1.startWD();  //start Watch Dog function. Timer starts at 0 and waits the previously passed in value (5000 ms).

  /*** P1 MODULES INITIALISATION
  *********************************************************************************************************************************

    Installed  Modules: 1 DIGITAL INPUT / 2 RELAY OUTPUT / 3 ANALOG OUTPUT

  ***/

  while (!P1.init()) {}
  Serial.println(F("Main module started. Starting additional modules..."));


  pinMode(A5, INPUT);
  pinMode(A6, INPUT);
  pinMode(3, INPUT);
  pinMode(pingPin, OUTPUT);


  /*** ETHERNET AND SERVER INITIALISATION
  *********************************************************************************************************************************/

  while (Ethernet.linkStatus() == LinkOFF && ethernetAttempts < 5) {
    delay(1000);
    ethernetAttempts++;
    Serial.println(F("Waiting Ethernet cable to connect (5 seconds)..."));
  }

  //Ethernet.begin(mac, ip);
  Serial.print(F("Starting DHCP server..."));
  Ethernet.begin(mac);
  Serial.println(F("  DHCP assigned IP "));
  Serial.println(Ethernet.localIP());

  server.begin();

  IPAddress ip = Ethernet.localIP();
  Serial.print(F("To access the server, connect with Telnet client to "));
  Serial.print(ip);
  Serial.println(":8888");

  currentState = SHUTDWN;


  /*** SERVO START-UP DELAY
  *********************************************************************************************************************************/
  delay(1000);  // Stabilization delay

  currentGridLidPosition = temgrid_servo_ext_home;
  currentGripperPosition = gripper_servo_ext_home;

  linAct.write(phenomlid_linact_ext_home);
  gridLid.write(temgrid_servo_ext_home);
  rotator.write(semrot_servo_ext_home);
  gripper.write(gripper_servo_ext_home);

  // Attach servos after power is stable
  linAct.attach(linActPin);
  gridLid.attach(gridLidPin);
  rotator.attach(rotatorPin);
  gripper.attach(gripperPin);
  Serial.println(F(" Servos attached."));

  P1.writeAnalog(4095, 3, 2); //4095,3,2 = 10V in the 3rd output module output 2.
  Serial.print(F("Servo delay pin on HIGH..."));

  Serial.println(F("PLC fully started!"));
}

void loop() {

  is_there_an_emergency();



  /*** PROCESSING COMMAND RECEIVED VIA ETHERNET (SOCKET)
  *********************************************************************************************************************************/

  EthernetClient client = server.available();  // returns first client which has data to read or a 'false' client
  if (client) {                                // client is true only if it is connected and has data to read
    clientmsg = client.readStringUntil('\n');  // read the message incoming from one of the clients
    clientmsg.trim();                          // trim eventual \r
    Serial.print(F("Client sent this >> "));
    Serial.println(clientmsg);  // print the message to Serial Monitor
    //client.print(F("Received: "));  // this is only for the sending client
    //client.print(clientmsg);     // send the message to all connected clients

#ifndef ARDUINO_ARCH_SAM
    server.flush();  // flush the buffers
#endif               /* !defined(ARDUINO_ARCH_SAM) */

    //Watchdog reset
    P1.petWD();
    is_there_an_emergency();

    /*** MACHINE STATE CHANGING DUE TO RECEIVED COMMAND - MUST BE FULLY PARSED TO CHANGE STATE
    *********************************************************************************************************************************/
    if (!hvps_trigger_action) {
      if (clientmsg.length() < 7) {
        parseerror = true;
        client.print(F(". ERROR! Not enough characters to be parsed for any change."));
      } else if (clientmsg.substring(0, 7) == "MACSTAT") {
        client.print(F("MACSTAT:"));
        Serial.print(F("MACSTAT:"));
        client.print(stateNames[currentState]);
        Serial.println(stateNames[currentState]);
        clientmsg = "";
      } else if (clientmsg.substring(0, 7) == "SHUTDWN") {
        currentState = SHUTDWN;
      } else if (clientmsg.substring(0, 7) == "STANDBY") {
        currentState = STANDBY;
      } else if (clientmsg.substring(0, 7) == "PHLIDMV") {
        if (clientmsg.length() < 11) {
          parseerror = true;
          Serial.print(". ERROR! Not enough characters to be parsed for PHLIDMV request.");
        } else {
          currentState = PHLIDMV;
        }
      } else if (clientmsg.substring(0, 7) == "TEMPREP") {
        if (clientmsg.length() < 10) {
          parseerror = true;
          //client.print(". ERROR! Not enough characters to be parsed for TEMPREP request.");
        } else {
          currentState = TEMPREP;
        }
      } else if (clientmsg.substring(0, 7) == "SEMPREP") {
        if (clientmsg.length() < 10) {
          parseerror = true;
          //client.print(". ERROR! Not enough characters to be parsed for SEMPREP request.");
        } else {
          currentState = SEMPREP;
        }
      } else if (clientmsg.substring(0, 7) == "EXPOSUR") {
        currentState = EXPOSUR;
      } else if (clientmsg.substring(0, 7) == "TEMSTOR") {
        currentState = TEMSTOR;
      } else if (clientmsg.substring(0, 7) == "SEMSTOR") {
        currentState = SEMSTOR;
      } else {
        currentState = SHUTDWN;
        clientmsg = "";
        parseerror = true;
      }
    } else {
      if (clientmsg.substring(0, 7) == "SHUTDWN") {
        currentState = SHUTDWN;
      } else if (clientmsg.substring(0, 7) == "STANDBY") {
        currentState = STANDBY;
      } else {
        outputmsg("SYSTEMBUSY", client);
      }
    }
  }

  /*** MACHINE STATES AND THEIR IMPLICATIONS
    *********************************************************************************************************************************/
  is_there_an_emergency();

  switch (currentState) {
    case SHUTDWN:
      if (clientmsg != "") {
        outputmsg("MACSTAT:SHUTDWN", client);
      }
      phenomlid_linact = false;
      temgrid_servo = false;
      semrot_servo = false;
      vacpump_one = false;
      vacpump_two = false;
      hvps_power = false;
      printer_power = false;
      vibmotor_one = false;
      vibmotor_two = false;
      hvps_prepare = false;
      hvps_trigger = false;
      hvps_trigger_action = false;
      gridLidMoving = false;
      gripperMoving = false;
      currentGridLidPosition = temgrid_servo_ext_home;
      currentGripperPosition = gripper_servo_ext_home;
      hvps_voltage = 0;
      hvps_exptime = 0;
      /*
        phenomlid_linact_ext = phenomlid_linact_ext_home;
        linAct.write(phenomlid_linact_ext);
        temgrid_servo_ext = temgrid_servo_ext_home;
        gridLid.write(temgrid_servo_ext); //#TODO
        semrot_servo_ext = semrot_servo_ext_home;
        rotator.write(semrot_servo_ext);
        gripper_servo_ext = gripper_servo_ext_home;
        gripper.write(gripper_servo_ext); //#TODO
      */

      //testing slow actions for Grid Lid and  Gripper
      phenomlid_linact_ext = phenomlid_linact_ext_home;
      linAct.write(phenomlid_linact_ext);
      temgrid_servo_ext = temgrid_servo_ext_home;
      moveGridLidGradually(temgrid_servo_ext);
      semrot_servo_ext = semrot_servo_ext_home;
      rotator.write(semrot_servo_ext);
      gripper_servo_ext = gripper_servo_ext_home;
      moveGripperGradually(gripper_servo_ext);
      break;

    case STANDBY:
      if (clientmsg != "") {
        outputmsg("MACSTAT:STANDBY", client);
      }
      phenomlid_linact = false;
      temgrid_servo = false;
      semrot_servo = false;
      vacpump_one = false;
      vacpump_two = false;
      hvps_power = true;
      printer_power = true;
      vibmotor_one = false;
      vibmotor_two = false;
      hvps_prepare = false;
      hvps_trigger = false;
      hvps_trigger_action = false;
      hvps_voltage = 0;
      hvps_exptime = 0;

      //testing slow actions for Grid Lid and Gripper
      phenomlid_linact_ext = phenomlid_linact_ext_home;
      semrot_servo_ext = semrot_servo_ext_home;
      gripper_servo_ext = gripper_servo_ext_home;
      temgrid_servo_ext = temgrid_servo_ext_home;
     
      temgrid_servo = true;
      gripper_servo = true;
      moveGridLidGradually(temgrid_servo_ext);
      moveGripperGradually(gripper_servo_ext);
      linAct.write(phenomlid_linact_ext);
      rotator.write(semrot_servo_ext);
      break;

    case PHLIDMV:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 8) == "L") {
            phenomlid_linact_ext = clientmsg.substring(8, 11).toInt();
            phenomlid_linact = true;
            phenomlid_linact_action = true;
          } else {
            parseerror = true;
          }
        }
      }
      break;

    case TEMPREP:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 11) == "VAC1") {
            vacpump_one = true;
            outputmsg("VACPUMPONE1", client);
          } else if (clientmsg.substring(7, 8) == "L") {
            temgrid_servo_ext = clientmsg.substring(8, 11).toInt();
            temgrid_servo = true;
            moveGridLidGradually(temgrid_servo_ext);
            temgrid_servo_action = true;
          } else if (clientmsg.substring(7, 11) == "TEST") {
            photointerrutor = P1.readDiscrete(1, 1);  //Read the value of channel 1 in slot 1
            client.print("LASER");
            client.print(photointerrutor);
          } else {
            parseerror = true;
          }
        }
      }
      break;

    case SEMPREP:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 12) == "VAC1") {
            vacpump_two = true;
            outputmsg("VACPUMPTWO1", client);
          } else if (clientmsg.substring(7, 12) == "VAC0") {
            vacpump_two = false;
            outputmsg("VACPUMPTWO0", client);
          } else if (clientmsg.substring(7, 8) == "R") {
            semrot_servo_ext = clientmsg.substring(8, 11).toInt();
            semrot_servo = true;
            semrot_servo_action = true;
          } else if (clientmsg.substring(7, 11) == "TEST") {
            photointerrutor = P1.readDiscrete(1, 1);  //Read the value in slot 1 channel 1  (Slot, Channel)
            output_message = "LASER" + String(photointerrutor);
            outputmsg(output_message, client);
            output_message = "";
          } else if (clientmsg.substring(7, 11) == "TESD") {

            pinMode(pingPin, OUTPUT);
            digitalWrite(pingPin, LOW);
            delayMicroseconds(2);
            digitalWrite(pingPin, HIGH);
            delayMicroseconds(750);
            digitalWrite(pingPin, LOW);

            // The same pin is used to read the signal from the PING))): a HIGH pulse
            // whose duration is the time (in microseconds) from the sending of the ping
            // to the reception of its echo off of an object.
            pinMode(pingPin, INPUT);
            duration = pulseIn(pingPin, HIGH);


            output_message = "DISTANCE_mm_" + String(duration / 171.5);
            outputmsg(output_message, client);
            output_message = "";
          } else {
            parseerror = true;
          }
        }
      }
      break;

    case EXPOSUR:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 8) == "M") {
            if (clientmsg.substring(8, 9) == "1") {
              if (clientmsg.substring(9, 10) == "1") {
                vibmotor_one = true;
                outputmsg("VIBMOTONE1", client);
              } else {
                vibmotor_one = false;
                outputmsg("VIBMOTONE0", client);
              }
            } else if (clientmsg.substring(8, 9) == "2") {
              if (clientmsg.substring(9, 10) == "1") {
                vibmotor_two = true;
                outputmsg("VIBMOTTWO1", client);
              } else {
                vibmotor_two = false;
                outputmsg("VIBMOTTWO0", client);
              }
            } else if (clientmsg.substring(8, 9) == "3") {
              if (clientmsg.substring(9, 10) == "1") {
                vibmotor_one = true;
                vibmotor_two = true;
                outputmsg("VIBMOTBOTH1", client);
              } else {
                vibmotor_one = false;
                vibmotor_two = false;
                outputmsg("VIBMOTBOTH0", client);
              }
            }
          } else if (clientmsg.substring(7, 11) == "TEST") {
            photointerrutor = P1.readDiscrete(1, 1);  //Read the value of channel 1 in slot 1
            output_message = "LASER" + String(photointerrutor);
            outputmsg(output_message, client);
            output_message = "";
          } else if (clientmsg.substring(7, 19).length() > 11) {
            if ((clientmsg.substring(7, 8) == "V") && (clientmsg.substring(13, 14) == "T")) {
              hvps_voltage = clientmsg.substring(8, 13).toInt();
              hvps_exptime = clientmsg.substring(14, 19).toInt();

              output_message = "";
              /*
                output_message.concat("VOLTAGE");
                output_message.concat(String(hvps_voltage));
                output_message.concat("&TIME");
                output_message.concat(String(hvps_exptime));
              */

              output_message = "VOLTAGE" + String(hvps_voltage) + "&TIME" + String(hvps_exptime);
              outputmsg(output_message, client);
              output_message = "";
              hvps_trigger_action = true;
              procedurestarttime = millis();
            } else {
              parseerror = true;
            }
          } else {
            parseerror = true;
          }
        }
      }
      break;

    case TEMSTOR:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 11) == "VAC0") {
            vacpump_one = false;
            outputmsg("VACPUMPONE0", client);
          } else {
            parseerror = true;
          }
        }
      }
      break;

    case SEMSTOR:
      if (!hvps_trigger_action) {
        if (clientmsg != "") {
          if (clientmsg.substring(7, 8) == "G") {
            gripper_servo_ext = clientmsg.substring(8, 11).toInt();
            gripper_servo = true;
            moveGripperGradually(gripper_servo_ext);
            gripper_servo_action = true;
          } else if (clientmsg.substring(7, 11) == "VAC0") {
            vacpump_two = false;
            outputmsg("VACPUMPTWO0", client);
          } else {
            parseerror = true;
          }
        }
      }
      break;

  }  // end of switch

  is_there_an_emergency();

  updateGripperMovement();
  updateGridLidMovement();

  //Vacuum Pump #1 Evaluation - Slot 2, Channel 1
  if (vacpump_one) {
    P1.writeDiscrete(HIGH, 2, 1);  //Turn slot 2 channel 1 on
  } else {
    P1.writeDiscrete(LOW, 2, 1);  //Turn slot 2 channel 1 off
  }

  //Vacuum Pump #2 Evaluation - Slot 2, Channel 2
  if (vacpump_two) {
    P1.writeDiscrete(HIGH, 2, 2);  //Turn slot 2 channel 2 on
  } else {
    P1.writeDiscrete(LOW, 2, 2);  //Turn slot 2 channel 2 off
  }

  //High Voltage Power Supply Evaluation - Slot 2, Channel 3
  if (hvps_power) {
    P1.writeDiscrete(HIGH, 2, 3);  //Turn slot 2 channel 2 on
  } else {
    P1.writeDiscrete(LOW, 2, 3);  //Turn slot 2 channel 3 off
  }

  //3D Printer Power Evaluation - Slot 2, Channel 4
  if (printer_power) {
    P1.writeDiscrete(HIGH, 2, 4);  //Turn slot 2 channel 4 on
  } else {
    P1.writeDiscrete(LOW, 2, 4);  //Turn slot 2 channel 4 off
  }

  //HVPS Prepare Evaluation - Slot 2, Channel 5
  if (hvps_prepare) {
    P1.writeDiscrete(HIGH, 2, 5);  //Turn slot 2 channel 5 on
  } else {
    P1.writeDiscrete(LOW, 2, 5);  //Turn slot 2 channel 5 off
  }

  //HVPS Trigger Evaluation - Slot 2, Channel 6
  if (hvps_trigger) {
    P1.writeDiscrete(HIGH, 2, 6);  //Turn slot 2 channel 6 on
  } else {
    P1.writeDiscrete(LOW, 2, 6);  //Turn slot 2 channel 6 off
  }

  //Vibration Motor ONE Evaluation - Slot 2, Channel 7
  if (vibmotor_one) {
    P1.writeDiscrete(HIGH, 2, 7);  //Turn slot 2 channel 7 on
  } else {
    P1.writeDiscrete(LOW, 2, 7);  //Turn slot 2 channel 7 off
  }

  //Vibration Motor TWO Evaluation - Slot 2, Channel 8
  if (vibmotor_two) {
    P1.writeDiscrete(HIGH, 2, 8);  //Turn slot 2 channel 8 on
  } else {
    P1.writeDiscrete(LOW, 2, 8);  //Turn slot 2 channel 8 off
  }

  //EXPOSURE PROCEDURE
  if (hvps_trigger_action) {
    //hvpsactivation(hvps_voltage, hvps_exptime, exposurestarttime);
    hvpsactivation();
  }


  //Phenom Lid Linear Actuator Evaluation - Slot 4, channel 1
  if (phenomlid_linact_action == true) {
    if (phenomlid_linact) {
      //P1.writePWM(phenomlid_linact_ext, PWM_FREQUENCY, 4, 1);
      linAct.write(phenomlid_linact_ext);
      output_message = "PHENOMACT" + String(phenomlid_linact_ext);
      outputmsg(output_message, client);
      output_message = "";
    }
    phenomlid_linact_action = false;
  }

  //TEM Lid Opener Evaluation - Slot 4, channel 2
  if (temgrid_servo_action == true) {
    if (temgrid_servo) {
      //P1.writePWM(temgrid_servo_ext, PWM_FREQUENCY, 4, 2);
      //gridLid.write(temgrid_servo_ext);
      output_message = "TEMLID" + String(temgrid_servo_ext);
      outputmsg(output_message, client);
      output_message = "";
    }
    temgrid_servo_action = false;
  }

  //SEM Rotator Evaluation - Slot 4, channel 3
  if (semrot_servo_action == true) {
    if (semrot_servo) {
      //P1.writePWM(semrot_servo_ext, PWM_FREQUENCY, 4, 3);
      rotator.write(semrot_servo_ext);
      output_message = "SEMROT" + String(semrot_servo_ext);
      outputmsg(output_message, client);
      output_message = "";
    }
    semrot_servo_action = false;
  }

  //Gripper Evaluation - Slot 4, channel 4
  if (gripper_servo_action == true) {
    if (gripper_servo) {
      //P1.writePWM(gripper_servo_ext, PWM_FREQUENCY, 4, 4);
      //gripper.write(gripper_servo_ext);
      //gripper_endtime = millis() + 2000; // unsigned long
      moveGripperGradually(gripper_servo_ext);

      output_message = "GRIPPER" + String(gripper_servo_ext);
      outputmsg(output_message, client);
      output_message = "";
      int pos = 0;
    }
    gripper_servo_action = false;
  }



  //Watchdog reset
  P1.petWD();
  is_there_an_emergency();



  /*** ERROR EVALUATION AND REPLIES
    *********************************************************************************************************************************/

  if (parseerror) {
    client.print("ERR-PARSE");
  }


  client.println();  //Adding an Endline character to the message sent to the client.
  client.stop();
  clientmsg = "";
  parseerror = false;
}  // end of loop()

/*** FUNCTIONS
    *********************************************************************************************************************************/

void is_there_an_emergency() {
  if (!P1.readDiscrete(1, 2) && debug == false) {  //Read the value of channel 2 in slot 1
    Serial.println(F("EMERGENCY DETECTED! HALTING THE SYSTEM!"));
    emergency_stop = true;
  }
  if (emergency_stop) {
    currentState = SHUTDWN;
    phenomlid_linact = false;
    temgrid_servo = false;
    semrot_servo = false;
    vacpump_one = false;
    vacpump_two = false;
    hvps_power = false;
    printer_power = false;
    vibmotor_one = false;
    vibmotor_two = false;
    hvps_prepare = false;
    hvps_trigger = false;
    hvps_trigger_action = false;
    gridLidMoving = false;
    gripperMoving = false;
    currentGridLidPosition = temgrid_servo_ext_home;
    currentGripperPosition = gripper_servo_ext_home;
    hvps_voltage = 0;
    hvps_exptime = 0;
    /*
      phenomlid_linact_ext = phenomlid_linact_ext_home;
      linAct.write(phenomlid_linact_ext);
      temgrid_servo_ext = temgrid_servo_ext_home;
      gridLid.write(temgrid_servo_ext);
      semrot_servo_ext = semrot_servo_ext_home;
      rotator.write(semrot_servo_ext);
      gripper_servo_ext = gripper_servo_ext_home;
      gripper.write(gripper_servo_ext);
    */
    P1.configWD(500, HOLD);  //Pass in the timer value and HOLD will stop the CPU from executing code until a powercycle.
    P1.startWD();
  }
}

void outputmsg(String msg0, EthernetClient& client) {
  String msg1 = msg0;
  client.print(msg1);
  Serial.println(msg1);
}

void hvpsactivation() {
  unsigned long exposureendtime = procedurestarttime + 1000 + hvps_exptime;
  int expose_voltage = hvps_voltage * 0.1365;

  if (exposureendtime >= millis()) {
    hvps_prepare = true;
    P1.writeAnalog(expose_voltage, 3, 1);
    if (millis() > (procedurestarttime + 1000)) {
      hvps_trigger = true;

    }
  } else {
    hvps_prepare = false;
    hvps_trigger = false;
    hvps_trigger_action = false;
    vibmotor_one = false;
    vibmotor_two = false;
    hvps_voltage = 0;
    hvps_exptime = 0;
    P1.writeAnalog(0, 3, 1);
  }
}

// Function to initiate gradual movement of the gripper
void moveGripperGradually(int targetPosition) {
  targetGripperPosition = targetPosition;
  gripperMoving = true;
  lastGripperMoveTime = millis(); // Reset timer for immediate first step
}

// Function to initiate gradual movement of the grid lid
void moveGridLidGradually(int targetPosition) {
  targetGridLidPosition = targetPosition;
  gridLidMoving = true;
  lastGridLidMoveTime = millis(); // Reset timer for immediate first step
}

// Update gripper movement with variable speed
void updateGripperMovement() {
  if (!gripperMoving) return;

  // Determine the appropriate delay based on current position
  // Not the direction of movement
  int currentDelay;
  if (currentGripperPosition > GRIPPER_THRESHOLD) {
    currentDelay = GRIPPER_SLOW_DELAY;  // Slower when position > 80 (more closed)
  } else {
    currentDelay = GRIPPER_FAST_DELAY;  // Faster when position < 80 (more open)
  }

  // Check if it's time for the next step
  if (millis() - lastGripperMoveTime >= currentDelay) {
    lastGripperMoveTime = millis();

    // Move one step toward target
    if (currentGripperPosition < targetGripperPosition) {
      currentGripperPosition += min(GRIPPER_STEP_SIZE, targetGripperPosition - currentGripperPosition);
    } else if (currentGripperPosition > targetGripperPosition) {
      currentGripperPosition -= min(GRIPPER_STEP_SIZE, currentGripperPosition - targetGripperPosition);
    }

    // Move the servo
    gripper.write(currentGripperPosition);

    // Check if we've reached the target
    if (currentGripperPosition == targetGripperPosition) {
      gripperMoving = false;
    }
  }
}

// Update grid lid movement with variable speed
void updateGridLidMovement() {
  if (!gridLidMoving) return;

  // Determine the appropriate delay based on position
  int currentDelay;
  if (currentGridLidPosition > GRID_LID_THRESHOLD) {
    currentDelay = GRID_LID_SLOW_DELAY;  // Slower when near container (above threshold)
  } else {
    currentDelay = GRID_LID_FAST_DELAY;  // Faster when away from container (below threshold)
  }

  // Check if it's time for the next step
  if (millis() - lastGridLidMoveTime >= currentDelay) {
    lastGridLidMoveTime = millis();

    // Move one step toward target
    if (currentGridLidPosition < targetGridLidPosition) {
      currentGridLidPosition += min(GRID_LID_STEP_SIZE, targetGridLidPosition - currentGridLidPosition);
    } else if (currentGridLidPosition > targetGridLidPosition) {
      currentGridLidPosition -= min(GRID_LID_STEP_SIZE, currentGridLidPosition - targetGridLidPosition);
    }

    // Move the servo
    gridLid.write(currentGridLidPosition);

    // Check if we've reached the target
    if (currentGridLidPosition == targetGridLidPosition) {
      gridLidMoving = false;
    }
  }
}
