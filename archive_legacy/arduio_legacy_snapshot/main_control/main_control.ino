#include <Servo.h>

// ======================================================
// 腳位定義
// ======================================================

// ==================== 步進馬達 ====================

// 第一顆步進馬達
const int ENA3 = 36;
const int DIR3 = 37;
const int PUL3 = 38;

// 第二顆步進馬達
const int ENA2 = 39;
const int DIR2 = 40;
const int PUL2 = 41;

// 第三顆步進馬達
const int ENA1 = 42;
const int DIR1 = 43;
const int PUL1 = 44;

// 第四顆步進馬達
const int ENA4 = 45;
const int DIR4 = 46;
const int PUL4 = 47;


// ==================== Servo ====================

// Servo1 → Pin 2
// Servo2 → Pin 3
// Servo3 → Pin 4
// Servo4 → Pin 5

Servo servo1;
Servo servo2;
Servo servo3;
Servo servo4;


// ==================== 按鈕 / 選擇開關 ====================

const int RED_BTN = 26;
const int GREEN_BTN = 27;
const int SELECT_SW = 28;

const int GREEN_LAMP = 29;
const int RED_LAMP = 30;
const int YELLOW_LAMP = 31;

const int YELLOW_BTN = 32;


// ======================================================
// Servo 控制參數
// ======================================================

// Normal 花生通過
// Servo 維持 135°
const int SERVO_NORMAL_ANGLE = 135;

// Mold / Small 篩除
// Servo 移動到 45°
const int SERVO_REJECT_ANGLE = 45;

// Servo 到 45° 後
// 1 秒後自動回到 135°
const unsigned long SERVO_ACTIVE_TIME = 1300;


// ======================================================
// Servo 狀態
// ======================================================

// 記錄 Servo 是否正在 45° 作動
bool servo1Active = false;
bool servo2Active = false;
bool servo3Active = false;
bool servo4Active = false;


// 記錄 Servo 到達 45° 的時間
unsigned long servo1StartTime = 0;
unsigned long servo2StartTime = 0;
unsigned long servo3StartTime = 0;
unsigned long servo4StartTime = 0;


// ======================================================
// 馬達控制參數
// ======================================================

// 馬達旋轉一圈所需脈衝
const long stepsPerRevolution = 51200;

// 每個脈衝 HIGH / LOW 時間
const unsigned int pulseDelayUs = 400;


// ======================================================
// 步進馬達目前理論位置
// ======================================================

long currentSteps1 = 0;
long currentSteps2 = 0;
long currentSteps3 = 0;
long currentSteps4 = 0;


// ======================================================
// 連續運轉狀態
// ======================================================

// R = 右
// L = 左
// S = 停止

char continuousMode = 'S';

// 選擇開關：LOW = L，HIGH = R。綠色按鈕依此方向啟動。
char selectedDirection = 'L';


// 馬達理論方向
int continuousDirection1 = 0;
int continuousDirection2 = 0;


// ======================================================
// 按鈕上一個狀態
// ======================================================

bool lastRed = HIGH;
bool lastGreen = HIGH;
bool lastYellow = HIGH;
bool lastSelect = HIGH;


// ======================================================
// Serial 暫存
// ======================================================

String serialBuffer = "";

// Python 回報的異常狀態。異常只能由 Python 重新檢查後解除。
bool faultActive = false;
unsigned long lastYellowBlinkTime = 0;
bool yellowLampState = false;
const unsigned long YELLOW_BLINK_INTERVAL = 400;


// ======================================================
// setup
// ======================================================

void setup() {

  // ==================================================
  // Serial
  // ==================================================

  Serial.begin(115200);


  // ==================================================
  // 步進馬達腳位
  // ==================================================

  pinMode(PUL1, OUTPUT);
  pinMode(DIR1, OUTPUT);
  pinMode(ENA1, OUTPUT);

  pinMode(PUL2, OUTPUT);
  pinMode(DIR2, OUTPUT);
  pinMode(ENA2, OUTPUT);

  pinMode(PUL3, OUTPUT);
  pinMode(DIR3, OUTPUT);
  pinMode(ENA3, OUTPUT);

  pinMode(PUL4, OUTPUT);
  pinMode(DIR4, OUTPUT);
  pinMode(ENA4, OUTPUT);


  // PUL 初始 LOW
  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);
  digitalWrite(PUL3, LOW);
  digitalWrite(PUL4, LOW);


  // 啟用步進馬達驅動器
  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);
  digitalWrite(ENA3, HIGH);
  digitalWrite(ENA4, HIGH);


  // ==================================================
  // Servo
  // ==================================================

  servo1.attach(2);
  servo2.attach(3);
  servo3.attach(4);
  servo4.attach(5);


  // 開機時全部 Servo 到 135°
  servo1.write(SERVO_NORMAL_ANGLE);
  servo2.write(SERVO_NORMAL_ANGLE);
  servo3.write(SERVO_NORMAL_ANGLE);
  servo4.write(SERVO_NORMAL_ANGLE);


  servo1Active = false;
  servo2Active = false;
  servo3Active = false;
  servo4Active = false;


  // ==================================================
  // 按鈕
  // ==================================================

  pinMode(RED_BTN, INPUT_PULLUP);
  pinMode(GREEN_BTN, INPUT_PULLUP);
  pinMode(SELECT_SW, INPUT_PULLUP);
  pinMode(YELLOW_BTN, INPUT_PULLUP);


  // ==================================================
  // 指示燈
  // ==================================================

  pinMode(GREEN_LAMP, OUTPUT);
  pinMode(RED_LAMP, OUTPUT);
  pinMode(YELLOW_LAMP, OUTPUT);

  digitalWrite(GREEN_LAMP, LOW);
  digitalWrite(RED_LAMP, HIGH);
  digitalWrite(YELLOW_LAMP, LOW);


  // ==================================================
  // 開機方向
  // ==================================================

  lastSelect = digitalRead(SELECT_SW);
  selectedDirection = (lastSelect == LOW) ? 'L' : 'R';
  Serial.print("PY:DIRECTION:");
  Serial.println(selectedDirection);


  // ==================================================
  // 系統資訊
  // ==================================================

  Serial.println();
  Serial.println("Arduino 已啟動");
  Serial.println("--------------------------------");

  Serial.println("步進馬達：");
  Serial.println("綠色按鈕：依選擇開關方向啟動");
  Serial.println("紅色按鈕：停止");
  Serial.println();

  Serial.println("Serial：");
  Serial.println("L：馬達1、2同步反向旋轉");
  Serial.println("R：L 的相反方向");
  Serial.println("S：停止");
  Serial.println();

  Serial.println("步進馬達角度控制：");
  Serial.println("例如：1,20");
  Serial.println("例如：3,-90");
  Serial.println();

  Serial.println("Servo 控制：");
  Serial.println("servo1,45");
  Serial.println("servo2,45");
  Serial.println("servo3,45");
  Serial.println("servo4,45");
  Serial.println();

  Serial.println("Servo 45° 作動 1 秒後自動回到 135°");
  Serial.println("--------------------------------");
}


// ======================================================
// loop
// ======================================================

void loop() {

  // ==================================================
  // 讀取實體按鈕
  // ==================================================

  readButtons();


  // ==================================================
  // 讀取 Serial
  // ==================================================

  readSerialCommand();


  // ==================================================
  // 執行步進馬達連續旋轉
  // ==================================================

  runContinuousMovement();


  // ==================================================
  // 檢查 Servo 是否需要回到 135°
  // ==================================================

  updateServos();

  // 依實際運轉／停止／異常狀態控制燈號。
  updateStatusLamps();
}


// ======================================================
// 按鈕
// ======================================================

void readButtons() {

  // ==================================================
  // 綠色按鈕
  // ==================================================

  bool greenState = digitalRead(GREEN_BTN);

  if (greenState == LOW) {
    // 只在按下瞬間觸發一次
    if (lastGreen == HIGH) {
      Serial.println("PY:BUTTON:GREEN");
      Serial.print("GREEN 觸發 → 啟動 ");
      Serial.println(selectedDirection);
      if (!faultActive) {
        startSelectedDirection();
      } else {
        Serial.println("異常尚未由 Python 清除，拒絕啟動");
      }
    }
  }

  lastGreen = greenState;


  // ==================================================
  // 紅色按鈕
  // ==================================================

  bool redState = digitalRead(RED_BTN);

  if (redState == LOW) {
    // 按下瞬間
    if (lastRed == HIGH) {
      Serial.println("PY:BUTTON:RED");
      Serial.println("RED 觸發 → 停止");
      stopContinuousMovement();
    }
  }

  lastRed = redState;


  // ==================================================
  // 黃色按鈕
  // ==================================================

  bool yellowState = digitalRead(YELLOW_BTN);

  if (yellowState == LOW) {
    if (lastYellow == HIGH) {
      Serial.println("PY:BUTTON:YELLOW");
      Serial.println("YELLOW 觸發");
    }
  }

  lastYellow = yellowState;


  // ==================================================
  // 方向選擇：LOW = L，HIGH = R
  // ==================================================

  bool selectState = digitalRead(SELECT_SW);

  if (selectState != lastSelect) {
    bool wasRunning = (continuousMode != 'S');
    selectedDirection = (selectState == LOW) ? 'L' : 'R';
    Serial.print("PY:DIRECTION:");
    Serial.println(selectedDirection);
    Serial.print("方向選擇：");
    Serial.println(selectedDirection);
    lastSelect = selectState;

    // 運轉中切換時先停止脈衝，再以新方向重新啟動。
    if (wasRunning && !faultActive) {
      stopContinuousMovement();
      delay(100);
      startSelectedDirection();
    }
  }
}


// ======================================================
// Serial 指令讀取
// ======================================================
// 所有指令都必須以 Enter 結束
//
// L
// R
// S
// servo1,45
// servo2,45
// servo3,45
// servo4,45
// 1,90
// 2,-90
//
// ======================================================


void readSerialCommand() {

  while (Serial.available() > 0) {

    char receivedChar = Serial.read();

    // ================================================
    // 忽略 CR
    // ================================================
    if (receivedChar == '\r') {
      continue;
    }

    // ================================================
    // 收到 Enter
    // ================================================
    if (receivedChar == '\n') {

      serialBuffer.trim();

      if (serialBuffer.length() > 0) {

        Serial.print("【Arduino 收到】：[");
        Serial.print(serialBuffer);
        Serial.println("]");

        processCommand(serialBuffer);
      }

      // 清空
      serialBuffer = "";

    } 
    else {

      // ================================================
      // 一般字元全部加入 Buffer
      // ================================================
      serialBuffer += receivedChar;
    }
  }
}


// ======================================================
// Serial 指令處理
// ======================================================

void processCommand(String input) {

    input.trim();

    Serial.print("【Arduino 收到】：[");
    Serial.print(input);
    Serial.println("]");

    if (input.length() == 0) {
        return;
    }

    // ==================================================
    // L / R / S
    // ==================================================

    if (input.equalsIgnoreCase("L")) {
        faultActive = false;
        startLeftMovement();
        return;
    }

    if (input.equalsIgnoreCase("R")) {
        faultActive = false;
        startRightMovement();
        return;
    }

    if (input.equalsIgnoreCase("S")) {
        stopContinuousMovement();
        return;
    }

    if (input.equalsIgnoreCase("START")) {
        faultActive = false;
        startSelectedDirection();
        return;
    }


    // ==================================================
    // 找逗號
    // ==================================================

    int commaIndex = input.indexOf(',');

    if (commaIndex == -1) {

        Serial.println("格式錯誤");
        Serial.println("步進馬達：1,90");
        Serial.println("Servo：servo1,45");
        Serial.println("滾輪：L / R / S");

        return;
    }


    // ==================================================
    // 取得逗號前後內容
    // ==================================================

    String deviceStr = input.substring(0, commaIndex);
    String valueStr = input.substring(commaIndex + 1);

    deviceStr.trim();
    valueStr.trim();

    // 轉成小寫
    String lowerDevice = deviceStr;
    lowerDevice.toLowerCase();

    // Python 狀態同步：STATE,RUNNING / STOPPED / FAULT
    if (lowerDevice == "state") {
        String stateValue = valueStr;
        stateValue.toLowerCase();
        if (stateValue == "fault") {
            faultActive = true;
            stopContinuousMovement();
            Serial.println("PY:STATE:FAULT");
        }
        else if (stateValue == "running") {
            faultActive = false;
            Serial.println("PY:STATE:RUNNING");
        }
        else if (stateValue == "stopped") {
            faultActive = false;
            Serial.println("PY:STATE:STOPPED");
        }
        return;
    }


    // ==================================================
    // Servo 指令
    //
    // servo1,45
    // servo2,45
    // servo3,45
    // servo4,45
    // ==================================================

    if (lowerDevice.startsWith("servo")) {

        processServoCommand(input);

        return;
    }


    // ==================================================
    // 步進馬達指令
    //
    // 1,90
    // 2,-90
    // 3,180
    // 4,0
    // ==================================================

    int motor = deviceStr.toInt();

    float targetAngle = valueStr.toFloat();


    // ==================================================
    // 除錯資訊
    // ==================================================

    Serial.print("步進馬達編號：");
    Serial.println(motor);

    Serial.print("目標角度：");
    Serial.println(targetAngle);


    // ==================================================
    // 馬達編號
    // ==================================================

    if (motor < 1 || motor > 4) {

        Serial.println("馬達編號錯誤，請輸入 1～4");

        return;
    }


    // ==================================================
    // 角度範圍
    // ==================================================

    if (targetAngle < -360.0 || targetAngle > 360.0) {

        Serial.println("角度超出範圍");

        return;
    }


    // ==================================================
    // 先停止連續模式
    // ==================================================

    if (continuousMode != 'S') {
        stopContinuousMovement();
    }


    // ==================================================
    // 控制步進馬達
    // ==================================================

    switch (motor) {

        case 1:

            moveMotorToAngle(
                PUL1,
                DIR1,
                ENA1,
                currentSteps1,
                targetAngle,
                1
            );

            break;


        case 2:

            moveMotorToAngle(
                PUL2,
                DIR2,
                ENA2,
                currentSteps2,
                targetAngle,
                2
            );

            break;


        case 3:

            moveMotorToAngle(
                PUL3,
                DIR3,
                ENA3,
                currentSteps3,
                targetAngle,
                3
            );

            break;


        case 4:

            moveMotorToAngle(
                PUL4,
                DIR4,
                ENA4,
                currentSteps4,
                targetAngle,
                4
            );

            break;
    }
}


// ======================================================
// Servo Serial 指令
// ======================================================
//
// 指令格式：
//
// servo1,45
// servo2,45
// servo3,45
// servo4,45
//
// Servo 到 45° 後
// 1 秒自動回到 135°
//
// ======================================================

void processServoCommand(String input) {

  input.trim();

  String lowerInput = input;
  lowerInput.toLowerCase();


  int commaIndex = lowerInput.indexOf(',');

  if (commaIndex == -1) {

    Serial.println("Servo 指令格式錯誤");
    Serial.println("例如：servo1,45");

    return;
  }


  String servoName = lowerInput.substring(
    0,
    commaIndex
  );

  String angleStr = lowerInput.substring(
    commaIndex + 1
  );

  servoName.trim();
  angleStr.trim();


  int angle = angleStr.toInt();


  // ==================================================
  // Servo 角度限制
  // ==================================================

  if (angle < 0 || angle > 180) {

    Serial.println("Servo 角度錯誤，請輸入 0～180");

    return;
  }


  // ==================================================
  // Servo1
  // ==================================================

  if (servoName == "servo1") {

    servo1.write(angle);

    Serial.print("Servo1 → ");
    Serial.print(angle);
    Serial.println("°");


    if (angle == SERVO_REJECT_ANGLE) {

      servo1Active = true;
      servo1StartTime = millis();

      Serial.println(
        "Servo1 → 45° 作動開始"
      );
    }


    return;
  }


  // ==================================================
  // Servo2
  // ==================================================

  if (servoName == "servo2") {

    servo2.write(angle);

    Serial.print("Servo2 → ");
    Serial.print(angle);
    Serial.println("°");


    if (angle == SERVO_REJECT_ANGLE) {

      servo2Active = true;
      servo2StartTime = millis();

      Serial.println(
        "Servo2 → 45° 作動開始"
      );
    }


    return;
  }


  // ==================================================
  // Servo3
  // ==================================================

  if (servoName == "servo3") {

    servo3.write(angle);

    Serial.print("Servo3 → ");
    Serial.print(angle);
    Serial.println("°");


    if (angle == SERVO_REJECT_ANGLE) {

      servo3Active = true;
      servo3StartTime = millis();

      Serial.println(
        "Servo3 → 45° 作動開始"
      );
    }


    return;
  }


  // ==================================================
  // Servo4
  // ==================================================

  if (servoName == "servo4") {

    servo4.write(angle);

    Serial.print("Servo4 → ");
    Serial.print(angle);
    Serial.println("°");


    if (angle == SERVO_REJECT_ANGLE) {

      servo4Active = true;
      servo4StartTime = millis();

      Serial.println(
        "Servo4 → 45° 作動開始"
      );
    }


    return;
  }


  // ==================================================
  // Servo 名稱錯誤
  // ==================================================

  Serial.println("Servo 編號錯誤");
  Serial.println("請輸入 servo1～servo4");
}


// ======================================================
// Servo 自動回位
// ======================================================
//
// 不使用 delay()
// 所以步進馬達仍然可以持續運作
//
// ======================================================

void updateServos() {

  unsigned long currentTime = millis();


  // ==================================================
  // Servo1
  // ==================================================

  if (
    servo1Active &&
    currentTime - servo1StartTime >= SERVO_ACTIVE_TIME
  ) {

    servo1.write(SERVO_NORMAL_ANGLE);

    servo1Active = false;

    Serial.println(
      "Servo1 → 1 秒完成 → 回到 135°"
    );
  }


  // ==================================================
  // Servo2
  // ==================================================

  if (
    servo2Active &&
    currentTime - servo2StartTime >= SERVO_ACTIVE_TIME
  ) {

    servo2.write(SERVO_NORMAL_ANGLE);

    servo2Active = false;

    Serial.println(
      "Servo2 → 1 秒完成 → 回到 135°"
    );
  }


  // ==================================================
  // Servo3
  // ==================================================

  if (
    servo3Active &&
    currentTime - servo3StartTime >= SERVO_ACTIVE_TIME
  ) {

    servo3.write(SERVO_NORMAL_ANGLE);

    servo3Active = false;

    Serial.println(
      "Servo3 → 1 秒完成 → 回到 135°"
    );
  }


  // ==================================================
  // Servo4
  // ==================================================

  if (
    servo4Active &&
    currentTime - servo4StartTime >= SERVO_ACTIVE_TIME
  ) {

    servo4.write(SERVO_NORMAL_ANGLE);

    servo4Active = false;

    Serial.println(
      "Servo4 → 1 秒完成 → 回到 135°"
    );
  }
}


// ======================================================
// L
// ======================================================
//
// 兩顆馬達接線完全相同
//
// Motor 1 DIR = LOW
// Motor 2 DIR = HIGH
//
// 才會實際一正一反
//
// ======================================================

void startSelectedDirection() {
  if (selectedDirection == 'R') {
    startRightMovement();
  }
  else {
    startLeftMovement();
  }
}

void startLeftMovement() {

  continuousMode = 'L';


  // 理論方向
  continuousDirection1 = -1;
  continuousDirection2 = 1;


  // 先拉低脈衝
  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);


  // DIR 相反
  digitalWrite(DIR1, HIGH);
  digitalWrite(DIR2, LOW);


  // 啟用
  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);


  delayMicroseconds(10);


  Serial.println(
    "L：馬達1、2開始同步反向旋轉"
  );
  Serial.println("PY:STATE:RUNNING");
}


// ======================================================
// R
// ======================================================

void startRightMovement() {

  continuousMode = 'R';


  // 理論方向
  continuousDirection1 = 1;
  continuousDirection2 = -1;


  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);


  // DIR 相反
  digitalWrite(DIR1, LOW);
  digitalWrite(DIR2, HIGH);


  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);


  delayMicroseconds(10);


  Serial.println(
    "R：馬達1、2開始同步反向旋轉"
  );
  Serial.println("PY:STATE:RUNNING");
}


// ======================================================
// 停止
// ======================================================

void stopContinuousMovement() {

  // 確保 PUL LOW
  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);


  if (continuousMode == 'S') {
    Serial.println("PY:STATE:STOPPED");
    return;
  }


  continuousMode = 'S';

  continuousDirection1 = 0;
  continuousDirection2 = 0;


  // 保持 Enable
  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);


  Serial.println(
    "S：馬達1、2已停止"
  );
  Serial.println("PY:STATE:STOPPED");


  Serial.print(
    "馬達1理論角度："
  );

  Serial.println(
    stepsToAngle(currentSteps1),
    2
  );


  Serial.print(
    "馬達2理論角度："
  );

  Serial.println(
    stepsToAngle(currentSteps2),
    2
  );
}


// ======================================================
// 狀態燈
// 運轉：綠燈長亮；停止：紅燈長亮；異常：黃燈閃爍
// ======================================================

void updateStatusLamps() {
  if (faultActive) {
    digitalWrite(GREEN_LAMP, LOW);
    digitalWrite(RED_LAMP, LOW);
    unsigned long now = millis();
    if (now - lastYellowBlinkTime >= YELLOW_BLINK_INTERVAL) {
      lastYellowBlinkTime = now;
      yellowLampState = !yellowLampState;
      digitalWrite(YELLOW_LAMP, yellowLampState ? HIGH : LOW);
    }
    return;
  }

  yellowLampState = false;
  digitalWrite(YELLOW_LAMP, LOW);
  if (continuousMode == 'S') {
    digitalWrite(GREEN_LAMP, LOW);
    digitalWrite(RED_LAMP, HIGH);
  }
  else {
    digitalWrite(GREEN_LAMP, HIGH);
    digitalWrite(RED_LAMP, LOW);
  }
}


// ======================================================
// 馬達1 + 馬達2 同步脈衝
// ======================================================

void runContinuousMovement() {

  if (continuousMode == 'S') {

    return;
  }


  // ==================================================
  // HIGH
  // ==================================================

  digitalWrite(PUL1, HIGH);
  digitalWrite(PUL2, HIGH);

  delayMicroseconds(pulseDelayUs);


  // ==================================================
  // LOW
  // ==================================================

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);

  delayMicroseconds(pulseDelayUs);


  // ==================================================
  // 理論位置
  // ==================================================

  currentSteps1 += continuousDirection1;
  currentSteps2 += continuousDirection2;
}


// ======================================================
// 單顆步進馬達指定角度
// ======================================================

void moveMotorToAngle(
  int pulPin,
  int dirPin,
  int enaPin,
  long &currentSteps,
  float targetAngle,
  int motorNumber
) {

  long targetSteps = angleToSteps(targetAngle);

  long stepDifference =
    targetSteps - currentSteps;


  if (stepDifference == 0) {

    Serial.print("馬達 ");
    Serial.print(motorNumber);
    Serial.println(
      " 已位於目標角度"
    );

    return;
  }


  // ==================================================
  // 設定方向
  // ==================================================

  if (stepDifference > 0) {

    digitalWrite(dirPin, HIGH);

  }
  else {

    digitalWrite(dirPin, LOW);
  }


  digitalWrite(enaPin, HIGH);

  digitalWrite(pulPin, LOW);

  delayMicroseconds(10);


  long stepsToMove = labs(stepDifference);


  // ==================================================
  // 輸出脈衝
  // ==================================================

  for (
    long stepCount = 0;
    stepCount < stepsToMove;
    stepCount++
  ) {

    digitalWrite(pulPin, HIGH);

    delayMicroseconds(pulseDelayUs);


    digitalWrite(pulPin, LOW);

    delayMicroseconds(pulseDelayUs);
  }


  // 更新理論位置
  currentSteps = targetSteps;


  Serial.print("馬達 ");
  Serial.print(motorNumber);
  Serial.print(" 已移動至：");

  Serial.print(
    stepsToAngle(currentSteps),
    2
  );

  Serial.println(" 度");
}


// ======================================================
// 角度 → Step
// ======================================================

long angleToSteps(float angle) {

  return (long)(
    angle *
    stepsPerRevolution /
    360.0
  );
}


// ======================================================
// Step → 角度
// ======================================================

float stepsToAngle(long steps) {

  return (
    (float)steps *
    360.0
  ) / stepsPerRevolution;
}
