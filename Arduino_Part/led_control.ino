#include <FastLED.h>

#define LED_PIN 6
#define NUM_LEDS 300

CRGB leds[NUM_LEDS];

void setup() {
  Serial.begin(9600);
  pinMode(LED_BUILTIN, OUTPUT);
  FastLED.addLeds<WS2811, LED_PIN, RGB>(leds, NUM_LEDS);
  FastLED.setBrightness(100);
  
  // 시작 시 LED 끄기
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
}

void loop() {
  if (Serial.available() >= 3) {  // RGB 3바이트 대기
    uint8_t r = Serial.read();
    uint8_t g = Serial.read();
    uint8_t b = Serial.read();
    
    // 신호 받음 표시 (보드 LED 깜빡)
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    
    // LED 색상 변경
    fill_solid(leds, NUM_LEDS, CRGB(r, g, b));
    FastLED.show();
  }
}
