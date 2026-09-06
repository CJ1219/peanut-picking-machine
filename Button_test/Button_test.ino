const int RED_BTN = 26;
const int GREEN_BTN = 27;
const int SELECT_SW = 28;

const int GREEN_LAMP = 29;
const int RED_LAMP = 30;
const int YELLOW_LAMP = 31;

const int YELLOW_BTN = 32;


// 上一次狀態
bool lastRed = HIGH;
bool lastGreen = HIGH;
bool lastYellow = HIGH;
bool lastSelect = HIGH;


void setup() {
  Serial.begin(115200);

  // 輸入
  pinMode(RED_BTN, INPUT_PULLUP);
  pinMode(GREEN_BTN, INPUT_PULLUP);
  pinMode(SELECT_SW, INPUT_PULLUP);
  pinMode(YELLOW_BTN, INPUT_PULLUP);

  // 輸出
  pinMode(GREEN_LAMP, OUTPUT);
  pinMode(RED_LAMP, OUTPUT);
  pinMode(YELLOW_LAMP, OUTPUT);

  // 開機全部熄滅
  digitalWrite(GREEN_LAMP, LOW);
  digitalWrite(RED_LAMP, LOW);
  digitalWrite(YELLOW_LAMP, LOW);

  // 顯示開機時目前模式
  if (digitalRead(SELECT_SW) == LOW) {
    Serial.println("模式：自動");
  } else {
    Serial.println("模式：手動");
  }
}


void loop() {

  // =========================
  // 綠色按鈕
  // =========================
  bool greenState = digitalRead(GREEN_BTN);

  if (greenState == LOW) {
    digitalWrite(GREEN_LAMP, HIGH);

    if (lastGreen == HIGH) {
      Serial.println("GREEN 觸發");
    }
  } else {
    digitalWrite(GREEN_LAMP, LOW);
  }

  lastGreen = greenState;


  // =========================
  // 紅色按鈕
  // =========================
  bool redState = digitalRead(RED_BTN);

  if (redState == LOW) {
    digitalWrite(RED_LAMP, HIGH);

    if (lastRed == HIGH) {
      Serial.println("RED 觸發");
    }
  } else {
    digitalWrite(RED_LAMP, LOW);
  }

  lastRed = redState;


  // =========================
  // 黃色按鈕
  // =========================
  bool yellowState = digitalRead(YELLOW_BTN);

  if (yellowState == LOW) {
    digitalWrite(YELLOW_LAMP, HIGH);

    if (lastYellow == HIGH) {
      Serial.println("YELLOW 觸發");
    }
  } else {
    digitalWrite(YELLOW_LAMP, LOW);
  }

  lastYellow = yellowState;


  // =========================
  // 自動 / 手動選擇開關
  // =========================
  bool selectState = digitalRead(SELECT_SW);

  if (selectState != lastSelect) {

    if (selectState == LOW) {
      Serial.println("模式：自動");
    } else {
      Serial.println("模式：手動");
    }

    lastSelect = selectState;
  }

  delay(10);
}