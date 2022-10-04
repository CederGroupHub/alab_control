//// Multiplexing
const int sourcePins[] = {2, 3, 4, 5, 6, 7};                          // pins that supply 5V to the drains of a "row" of phototransistors. assumed these are in order.
const int readPins[] = {8, 9, 10, 11, 12, 13};                        // pins that read the voltage at the sources of a "column" of phototransistors. assumed these are in order.
const int numSourcePins = sizeof(sourcePins) / sizeof(sourcePins[0]); // number of 'rows' in multiplex array
const int numReadPins = sizeof(readPins) / sizeof(readPins[0]);       // number of 'columns' in multiplex array

#define ON_THRESHOLD 150 // the minimum value (0-255) that a phototransistor must read to be considered "on"

//// Communication
// Serial
#define BAUDRATE 9600
// ethernet
static byte mymac[] = {0x74, 0x39, 0x70, 0x2D, 0x30, 0x31};
static byte myip[] = {192, 168, 1, 5};
