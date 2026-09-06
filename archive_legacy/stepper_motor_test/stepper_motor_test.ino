// ==================== 腳位定義 ====================

// 第一顆馬達
const int PUL1 = 39;
const int DIR1 = 38;
const int ENA1 = 37;

// 第二顆馬達
const int PUL2 = 36;
const int DIR2 = 35;
const int ENA2 = 34;

// 第三顆馬達
const int PUL3 = 33;
const int DIR3 = 32;
const int ENA3 = 31;

// 第四顆馬達
const int PUL4 = 42;
const int DIR4 = 41;
const int ENA4 = 40;


// ==================== 控制參數 ====================

// 馬達旋轉一圈所需脈衝數
const long stepsPerRevolution = 51200;

// 每個脈衝的高、低電位時間
const unsigned int pulseDelayUs = 500;

// R、L 指令執行時間：1000 ms = 1 秒
const unsigned long continuousDurationMs = 10000;

// 連續運轉開始時間
unsigned long continuousStartTime = 0;

// 使用步數記錄目前理論位置
long currentSteps1 = 0;
long currentSteps2 = 0;
long currentSteps3 = 0;
long currentSteps4 = 0;

// 'L' = 左轉
// 'S' = 停止
char continuousMode = 'S';

// 馬達 1、2 在連續模式下的方向
int continuousDirection1 = 0;
int continuousDirection2 = 0;

// 串列輸入暫存
String serialBuffer = "";


// ==================== 初始化 ====================

void setup() {
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

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);
  digitalWrite(PUL3, LOW);
  digitalWrite(PUL4, LOW);

  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);
  digitalWrite(ENA3, HIGH);
  digitalWrite(ENA4, HIGH);

  Serial.begin(115200);

  Serial.println("Arduino 已啟動");
  Serial.println("--------------------------------");
  Serial.println("角度控制：輸入 馬達編號,目標角度");
  Serial.println("例如：1,20 或 3,-90");
  Serial.println();
  Serial.println("R/r：馬達1正轉、馬達2反轉，執行1秒");
  Serial.println("L/l：馬達1反轉、馬達2正轉，執行1秒");
  Serial.println("S/s：立即停止馬達1、馬達2");
  Serial.println("--------------------------------");
}


// ==================== 主程式 ====================

void loop() {
  readSerialCommand();
  runContinuousMovement();
}


// ==================== 串列指令讀取 ====================

void readSerialCommand() {
  while (Serial.available() > 0) {
    char receivedChar = Serial.read();

    if (receivedChar == '\r') {
      continue;
    }

    // R、L、S 不需等待換行
    if (serialBuffer.length() == 0) {
      if (receivedChar == 'R' || receivedChar == 'r' ||
          receivedChar == 'L' || receivedChar == 'l' ||
          receivedChar == 'S' || receivedChar == 's') {

        processCommand(String(receivedChar));
        continue;
      }
    }

    if (receivedChar == '\n') {
      serialBuffer.trim();

      if (serialBuffer.length() > 0) {
        processCommand(serialBuffer);
      }

      serialBuffer = "";
    } else {
      serialBuffer += receivedChar;
    }
  }
}


// ==================== 指令處理 ====================

void processCommand(String input) {
  input.trim();

  if (input.length() == 0) {
    return;
  }

  if (input.equalsIgnoreCase("R")) {
    startRightMovement();
    return;
  }

  if (input.equalsIgnoreCase("L")) {
    startLeftMovement();
    return;
  }

  if (input.equalsIgnoreCase("S")) {
    stopContinuousMovement();
    return;
  }

  int commaIndex = input.indexOf(',');

  if (commaIndex == -1) {
    Serial.println("格式錯誤");
    Serial.println("請輸入例如：1,20 或 R、L、S");
    return;
  }

  String motorStr = input.substring(0, commaIndex);
  String angleStr = input.substring(commaIndex + 1);

  motorStr.trim();
  angleStr.trim();

  int motor = motorStr.toInt();
  float targetAngle = angleStr.toFloat();

  if (motor < 1 || motor > 4) {
    Serial.println("馬達編號錯誤，請輸入 1～4");
    return;
  }

  if (targetAngle < -360.0 || targetAngle > 360.0) {
    Serial.println("角度超出範圍，請輸入 -360～360 度");
    return;
  }

  // 執行角度控制前，停止連續旋轉
  if (continuousMode != 'S') {
    stopContinuousMovement();
  }

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


// ==================== R／L／S 控制 ====================

// R：馬達1正轉、馬達2反轉，執行1秒
void startRightMovement() {
  continuousMode = 'R';

  continuousDirection1 = 1;
  continuousDirection2 = -1;

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);

  // 依照目前實際接線設定
  digitalWrite(DIR1, LOW);
  digitalWrite(DIR2, LOW);

  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);

  delayMicroseconds(10);

  // 記錄開始時間
  continuousStartTime = millis();

  Serial.println("R：馬達1正轉、馬達2反轉，開始執行1秒");
}


// L：馬達1反轉、馬達2正轉，執行1秒
void startLeftMovement() {
  continuousMode = 'L';

  continuousDirection1 = -1;
  continuousDirection2 = 1;

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);

  // 依照目前實際接線設定
  digitalWrite(DIR1, HIGH);
  digitalWrite(DIR2, HIGH);

  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);

  delayMicroseconds(10);

  // 記錄開始時間
  continuousStartTime = millis();

  Serial.println("L：馬達1反轉、馬達2正轉，開始執行1秒");
}


// 停止發送脈衝
void stopContinuousMovement() {
  // 避免停止狀態重複輸出訊息
  if (continuousMode == 'S') {
    return;
  }

  continuousMode = 'S';

  continuousDirection1 = 0;
  continuousDirection2 = 0;

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);

  // 停止後保持馬達鎖定
  digitalWrite(ENA1, HIGH);
  digitalWrite(ENA2, HIGH);

  Serial.println("S：馬達1、馬達2已停止");

  Serial.print("馬達1目前理論角度：");
  Serial.println(stepsToAngle(currentSteps1), 2);

  Serial.print("馬達2目前理論角度：");
  Serial.println(stepsToAngle(currentSteps2), 2);
}


// 連續輸出脈衝
void runContinuousMovement() {
  if (continuousMode == 'S') {
    return;
  }

  // 超過1秒後自動停止
  if (millis() - continuousStartTime >= continuousDurationMs) {
    Serial.println("1秒運轉時間結束");
    stopContinuousMovement();
    return;
  }

  digitalWrite(PUL1, HIGH);
  digitalWrite(PUL2, HIGH);

  delayMicroseconds(pulseDelayUs);

  digitalWrite(PUL1, LOW);
  digitalWrite(PUL2, LOW);

  delayMicroseconds(pulseDelayUs);

  currentSteps1 += continuousDirection1;
  currentSteps2 += continuousDirection2;
}


// ==================== 指定角度控制 ====================

void moveMotorToAngle(
  int pulPin,
  int dirPin,
  int enaPin,
  long &currentSteps,
  float targetAngle,
  int motorNumber
) {
  long targetSteps = angleToSteps(targetAngle);
  long stepDifference = targetSteps - currentSteps;

  if (stepDifference == 0) {
    Serial.print("馬達 ");
    Serial.print(motorNumber);
    Serial.println(" 已位於目標角度，無需移動");
    return;
  }

  if (stepDifference > 0) {
    digitalWrite(dirPin, HIGH);
  } else {
    digitalWrite(dirPin, LOW);
  }

  digitalWrite(enaPin, HIGH);
  digitalWrite(pulPin, LOW);

  delayMicroseconds(10);

  long stepsToMove = labs(stepDifference);

  for (long stepCount = 0; stepCount < stepsToMove; stepCount++) {
    digitalWrite(pulPin, HIGH);
    delayMicroseconds(pulseDelayUs);

    digitalWrite(pulPin, LOW);
    delayMicroseconds(pulseDelayUs);
  }

  currentSteps = targetSteps;

  Serial.print("馬達 ");
  Serial.print(motorNumber);
  Serial.print(" 已移動至角度：");
  Serial.println(stepsToAngle(currentSteps), 2);
}


// ==================== 單位換算 ====================

long angleToSteps(float angle) {
  return (long)(angle * stepsPerRevolution / 360.0);
}

float stepsToAngle(long steps) {
  return ((float)steps * 360.0) / stepsPerRevolution;
}