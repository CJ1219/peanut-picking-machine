#include <Servo.h>

Servo servo;

void setup() {
  Serial.begin(9600);

  servo.attach(2);   // MG996R 訊號線接 Pin 2
  servo.write(90);   // 初始位置 90°
}

void loop() {
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == 't' || command == 'T') {
      servo.write(135);   // t / T = 135°
    }

    else if (command == 'f' || command == 'F') {
      servo.write(45);    // f / F = 45°
    }
  }
}