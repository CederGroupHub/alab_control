#include <config.h> // holds the board config values (pins, thresholds, etc)

bool isOn[numSourcePins][numReadPins] // 2d array of booleans that represent the state of each phototransistor. true = on, false = off.

    // the setup routine runs once when you press reset:
    void
    setup()
{
    // initialize serial communication at 9600 bits per second:
    Serial.begin(BAUDRATE);

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

bool send_state(int row, int col)
{
    // send the state of the phototransistor at the given row and column
    // returns true if the state was sent, false if it was not
    //
    // Example use:
    //
    //      sendSlotState(0, 2); // send the state of the phototransistor at row 0, column 2
    //
    //      >> "row=0 col=2 state=1\n"
    Serial.print("row=");
    Serial.print(row);
    Serial.print(" col=");
    Serial.print(col);
    Serial.print(" state=");
    Serial.println(isOn[slotIndex]);
}

void scan_and_update()
{
    // scan the multiplexing grid and update photodiode on state to 2d array "isOn"
    //
    // any time the state of a photodiode changes, the new state is sent over seriial computer
    for (int row = 0; row < numSourcePins; row++)
    {
        digitalWrite(sourcePins[row], HIGH);
        for (int col = 0; col < numReadPins; j++)
        {
            int val = analogRead(readPins[col]);
            bool newState = val > ON_THRESHOLD;
            if (newState != isOn[row][col])
            {
                isOn[row][col] = newState;
                sendState(row * numReadPins + col);
            }
        }
        digitalWrite(sourcePins[i], LOW);
    }
}

void parse_input()
{
    // Expected input formats:
    //
    //  "a" - return state of all phototransistors
    //      >> "a\n"
    //      << "row=0 col=0 state=1\n"
    //      << "row=0 col=1 state=0\n"
    //      << ...
    //      << "row=(finalrow) col=(finalcol) state=1\n"
    //
    //  "s" - return state of a single phototransistor. This will be followed by a row and column number like so:
    //      >> "s 0 2\n"
    //      << "row=0 col=2 state=1\n"
    while
        Serial.available() > 0
        {
            char query = Serial.read();
            switch (query)
            {
            case "a": // all
                for (int row = 0; row < numSourcePins; row++)
                {
                    for (int col = 0; col < numReadPins; col++)
                    {
                        send_state(row, col);
                    }
                }
            case "s": // specific
                int row = Serial.parseInt(SKIP_WHITESPACE);
                int col = Serial.parseInt(SKIP_WHITESPACE);
                send_state(row, col);
                break;
            default:
                break;
            }

            // say what you got:
        }
}

void loop()
{
    // main loop
    scan_and_update();
    parse_input();
}
