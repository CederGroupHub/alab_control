// Quick FSR / force-sensor test
#define FORCE_PIN A0

void setup() {
  Serial.begin(9600);
  pinMode(FORCE_PIN, INPUT_PULLUP);
  Serial.println(F("Force sensor test ready"));
}

void loop() {
  Serial.println(analogRead(FORCE_PIN));
  delay(200);
}
