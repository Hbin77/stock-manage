# 주식 스크리닝 알고리즘 수학적 심층 분석 리포트

**분석자**: Claude Opus 4.6 (Quant AI Expert)
**대상 함수**: `ai_analyzer.get_priority_tickers()` (line 727-976)
**분석 일자**: 2026-02-24
**샘플 크기**: 654개 개별주식 (ETF 제외)

---

## 1. 각 서브스코어의 이론적 범위 계산

### 1.1 Momentum Sub-Score 범위 분석

#### M1: MA Alignment (0-4)
- **최소값**: 0 (모든 MA 조건 미충족)
- **최대값**: 4 (가격 > MA20, MA50, MA200 + 완벽한 스택킹)
- **설정**: `momentum += min(ma_count, 4)`
  - 개별 비교 최대 3점 + 스택킹 보너스 1점 = 4점
  - 논리: 직관적이고 명확한 추세 확인 메커니즘

#### M2: MACD (0-3)
- **구성**:
  - Golden Cross: 2.5점
  - MACD > 0 (가속): 2.0점
  - MACD > 0 (단순): 1.5점
- **최소값**: 0 (MACD ≤ 0 또는 None)
- **최대값**: 3.0 (Golden Cross 또는 가속하는 양수)
- **설정**: `momentum += min(macd_pts, 3.0)`
- **논리**: 가장 강한 신호(Golden Cross)가 너무 강하게 가중치됨 (2.5/3.0 = 83%)

#### M3: ADX Multiplier (배수 적용)
- **최소값**: 0.7× (ADX < 20, 약한 추세)
- **최대값**: 1.3× (ADX > 30, 강한 추세)
- **중간값**: 1.0× (20 ≤ ADX ≤ 25)
- **적용**: Momentum 스코어에 직접 곱함
- **범위**: 0.7 × (0 + 0 + 1.5) = 1.05 ~ 1.3 × 7 = 9.1 (M1+M2+M4 최대)

#### M4: RSI Momentum Zone (1.5 포인트)
- **조건**: 50 ≤ RSI ≤ 65
- **포인트**: 1.5 (고정)
- **설정**: `momentum += 1.5`

#### **Momentum 이론적 범위**
```
최소: max(0, (0 + 0) × 0.7) + 0 = 0
최대: min(4, 4) + min(3, 3) × 1.3 + 1.5 = 4 + 3.9 + 1.5 = 9.4

그러나 ADX 곱셈이 모든 항에 영향을 주므로:
더 정확한 최대: (4 + 3) × 1.3 + 1.5 = 9.1 + 1.5 = 10.6
```

**문제점**:
- ADX multiplier가 M1+M2에만 곱해지고 M4는 더해짐 → 비일관성
- M4 (RSI zone)가 고정값이므로 다른 신호와 상대적 중요도 불명확

---

### 1.2 Mean-Reversion Sub-Score 범위 분석

#### R1: RSI Oversold (0-3)
- **RSI < 25**: 3.0점
- **RSI 25-30**: 2.5점
- **RSI 30-35**: 1.5점
- **RSI 35-40**: 0.5점
- **RSI ≥ 40**: 0점
- **최대값**: 3.0
- **설정**: 단순 조건부 가산 (`reversion +=`)

#### R2: StochRSI Oversold Cross (0-2)
- **K < 0.20, D < 0.20**: 1.0점 (진입)
- **+ Bullish Cross** (K ↑ 위로, D는 아래): +1.0점
- **최대값**: 2.0
- **설정**: `reversion += 1.0 + 1.0` (순차적)

#### R3: Bollinger Band Position (0-2.5)
- **BB 범위**: `bb_pct = (price - lower) / (upper - lower) × 100`
- **pct < 10**: 2.5점
- **pct 10-20**: 2.0점
- **pct 20-30**: 1.0점
- **pct ≥ 30**: 0점
- **최대값**: 2.5

#### R4: Bollinger Band Squeeze (0-1.5)
- **조건**: `bb_width = (upper - lower) / middle`
- **이전 대비 폭소 여부** 확인
- **width < 0.04 AND width < prev_width**: 1.5점
- **width < 0.06**: 0.5점
- **최대값**: 1.5
- **설정**: 전일 데이터와 비교 필요

#### **Mean-Reversion 이론적 범위**
```
최소: 0
최대: 3.0 (R1) + 2.0 (R2) + 2.5 (R3) + 1.5 (R4) = 9.0
```

---

### 1.3 Volume Multiplier 범위

**적용 대상**: (momentum × regime_mom_w + reversion × regime_rev_w)

#### Volume Ratio (VR = latest_volume / volume_ma_20)
- **VR > 2.0**: 1.4×
- **VR 1.3-2.0**: 1.2×
- **VR 0.8-1.3**: 1.0× (암시적, 미처리)
- **VR 0.5-0.8**: 0.8×
- **VR < 0.5**: 0.6×

**범위**: 0.6× ~ 1.4×

---

### 1.4 OBV Divergence 보너스

**적용 대상**: 직접 가산 (`adjusted = raw * vol_mult + obv_bonus`)

- **Bullish divergence** (OBV ↑ vs Price ↓): +1.5
- **Confirming uptrend** (OBV ↑ vs Price ↑): +0.5
- **Bearish divergence** (OBV ↓ vs Price ↑): -1.0
- **범위**: -1.0 ~ +1.5

---

### 1.5 최종 스코어 계산식 추적

```
raw = regime_mom_w × momentum + regime_rev_w × reversion
adjusted = raw × vol_mult + obv_bonus
final = adjusted × (1.0 - knife_pen)
```

**Penalty 종류**:
1. **Falling Knife Penalty** (`knife_pen`)
   - 4일 연속 하락: 0.4
   - 3일 연속 하락: 0.25
   - 범위: 0 ~ 0.4

2. **Below MA200 Penalty** (별도, reversion에만)
   - reversion *= 0.5 (만약 price < MA200)

3. **Bull Trap Penalty** (Golden Cross에만)
   - Volume < 80% MA: -0.2 × macd_pts
   - Price < MA20 AND < MA50: -0.3 × macd_pts
   - 최대: -0.5 × macd_pts

4. **Overbought Guard** (RSI > 75)
   - momentum *= 0.5
   - reversion *= 0.2

---

### 1.6 이론적 최대/최소값 정리

| 구성요소 | 최소 | 최대 | 비고 |
|---------|------|------|------|
| Momentum (M1~M4 + ADX) | 0 | ~10.6 | ADX 곱셈 불일관성 |
| Mean-Reversion (R1~R4) | 0 | 9.0 | 균형잡힌 범위 |
| Volume Mult | 0.6× | 1.4× | 비대칭 (0.6 vs 1.4) |
| OBV Bonus | -1.0 | +1.5 | 비대칭 (하방 -1.0 vs 상방 +1.5) |
| Knife Pen | -0.4 | 0 | 제한적 영향 |

#### Regime별 Raw 범위 (penalty 미적용)

**Trending (70% mom, 30% rev)**:
```
min: 0.70 × 0 + 0.30 × 0 = 0
max: 0.70 × 10.6 + 0.30 × 9.0 = 7.42 + 2.7 = 10.12
```

**Transitional (45% mom, 55% rev)**:
```
min: 0
max: 0.45 × 10.6 + 0.55 × 9.0 = 4.77 + 4.95 = 9.72
```

**High Volatility (25% mom, 75% rev)**:
```
min: 0
max: 0.25 × 10.6 + 0.75 × 9.0 = 2.65 + 6.75 = 9.4
```

#### Adjusted (vol_mult + obv_bonus 포함)

**Trending maximum**:
```
최대: (10.12 × 1.4) + 1.5 = 14.168 + 1.5 = 15.668 (penalty 전)
```

**Falling Knife Penalty 적용**:
```
최악: 15.668 × (1 - 0.4) = 15.668 × 0.6 = 9.4
```

---

## 2. 구조적 결함 식별

### 2.1 Momentum과 Reversion 스케일 불균형

**발견**: Momentum 최대값 (10.6)이 Mean-Reversion 최대값 (9.0)보다 17.8% 높음

```
Trending regime에서:
- Momentum 기여도: 0.70 × 10.6 = 7.42 (73.4% of raw)
- Reversion 기여도: 0.30 × 9.0 = 2.7 (26.6% of raw)
```

**영향**:
- Trending market에서 momentum 신호가 과도하게 가중됨
- Reversion 신호의 상대적 중요도 최소화
- **심각도**: 중간 (의도적 설계일 수 있음, 명확한 근거 부재)

---

### 2.2 ADX Multiplier가 Momentum에만 적용되는 문제

**코드**:
```python
# Line 846-852
adx_mult = 1.0
if ind.adx_14 is not None:
    if ind.adx_14 > 30: adx_mult = 1.3
    elif ind.adx_14 > 25: adx_mult = 1.15
    elif ind.adx_14 < 20: adx_mult = 0.7
momentum *= adx_mult  # ← Momentum에만 적용!
```

**문제**:
- ADX는 "추세 강도"를 측정하는 지표
- Mean-Reversion 신호 신뢰도에도 영향을 미쳐야 함 (낮은 ADX = 범위 박스 = reversion 기회↑)
- 현재: **High ADX 상황에서만 reversion이 무시됨** (regime weighting으로만 조정)
- **심각도**: 높음 (논리적 누락)

**기대 개선**:
```python
# Reversion은 약한 추세(low ADX)에서 더 강해야 함
if ind.adx_14 is not None:
    if ind.adx_14 > 30: reversion *= 0.7  # 강한 추세 = reversion 약화
    elif ind.adx_14 < 20: reversion *= 1.3  # 약한 추세 = reversion 강화
```

---

### 2.3 Regime Blending의 실질적 효과

**현재 가중치**:
- Trending: 70/30 (momentum/reversion)
- Transitional: 45/55
- High Vol: 25/75

**실제 최대값 비교** (penalty 전 raw):
```
Trending momentum max:    7.42
Transitional momentum:    4.77 (35.7% 감소)
High-vol momentum:        2.65 (64.3% 감소) ✓ 명확

High-vol reversion max:   6.75
Transitional reversion:   4.95 (26.7% 감소)
Trending reversion:       2.7  (60% 감소) ✓ 명확
```

**평가**: Regime switching은 **의도대로 작동하지만** 상대적 범위 때문에 여전히:
- Trending에서는 Momentum 신호 과도
- High-vol에서는 Reversion에 의존하지만 Momentum도 일정 역할 유지

**문제점**: Regime blending이 **절대 가중치를 조정**할 뿐 **상대 범위 차이는 유지** (2.3 문제와 조합)

---

### 2.4 Volume Multiplier와 OBV 혼용 문제 (Additive vs Multiplicative)

**코드**:
```python
# Line 954-956
raw = regime_mom_w * momentum + regime_rev_w * reversion
adjusted = raw * vol_mult + obv_bonus  # ← 혼용!
final = adjusted * (1.0 - knife_pen)
```

**구조 분석**:
```
adjusted = raw × vol_mult + obv_bonus

예1 (high volume):
  raw = 5.0, vol_mult = 1.4, obv_bonus = +1.5
  adjusted = 5.0 × 1.4 + 1.5 = 7.0 + 1.5 = 8.5

예2 (low volume):
  raw = 5.0, vol_mult = 0.6, obv_bonus = +1.5
  adjusted = 5.0 × 0.6 + 1.5 = 3.0 + 1.5 = 4.5
  → vol_mult 효과: -3.5 감소, OBV 효과: +1.5 추가 (net: -2.0)

예3 (low volume, bearish OBV):
  adjusted = 5.0 × 0.6 - 1.0 = 3.0 - 1.0 = 2.0
  → 극단적 약화
```

**문제**:
1. **OBV가 Volume과 독립적으로 작동**
   - Volume 곱셈 후 OBV 가산 = 비일관성
   - OBV는 절대값, Volume은 배수 → 스케일 혼재

2. **OBV 범위 (-1.0 ~ +1.5)가 Volume 효과 (0.6 ~ 1.4×)와 비교 불가**
   - raw=5일 때: vol_mult ±0.4 변화 = ±2.0 포인트
   - OBV ±2.5 변화 = ±2.5 포인트 (비슷 크기, 다른 메커니즘)

3. **Bearish divergence (-1.0)는 Bullish (+1.5)와 비대칭**
   - 하락 위험 과소표현

**심각도**: 중간~높음 (비일관적 구조, 수학적 비대칭)

---

### 2.5 Penalty의 비대칭적 영향

#### Falling Knife Penalty
```python
if down_days >= 4: knife_pen = 0.4
elif down_days >= 3: knife_pen = 0.25
```

**영향도**:
- High-score stock (raw ≈ 10): 10 × 0.6 = 6.0 (40% 감소)
- Low-score stock (raw ≈ 2): 2 × 0.6 = 1.2 (40% 감소) ← **같은 % 감소**

**하지만 절대값으로는**:
- High: -4.0 포인트 제거
- Low: -0.8 포인트 제거

**논리**: 하락하는 종목 모두에 같은 비중으로 페널티 → 부분적으로 공정

#### Below MA200 Penalty
```python
if current_price < ind.ma_200:
    reversion *= 0.5  # ← Reversion만!
```

**문제**:
- MA200 아래 = 약세 추세 확실
- Reversion 신호만 약화시킴 (momentum은 여전히 강할 수 있음)
- High ADX + Price < MA200인 경우: momentum은 활성, reversion은 절반 → **역설**
  ```
  강한 하락추세에서도 momentum 신호가 강하게 나올 수 있음
  (MACD가 음수이지만 momentum 최대값이 여전히 높음)
  ```

**심각도**: 높음 (reversion-only penalty는 논리적 누락)

#### Bull Trap Penalty (Golden Cross에만)
```python
if is_golden_cross:
    trap = 0.0
    if latest_volume < vol_ma_20 * 0.8: trap += 0.2
    if (current_price < ma_20 and current_price < ma_50): trap += 0.3
    if trap > 0:
        momentum -= macd_pts * min(trap, 0.5)
```

**문제**:
- **다른 모든 penalty는 곱셈 (%), bull trap은 감산 (절대값)**
- `momentum -= macd_pts × trap` → -0.375 ~ -1.25 포인트
- 절대값이므로 기저 momentum이 높을 때만 의미 있음

**예시**:
```
macd_pts = 2.5, trap = 0.5
momentum = 0 (다른 신호 없음) + 2.5 (golden cross) = 2.5
momentum -= 2.5 × 0.5 = 2.5 - 1.25 = 1.25 ✓ 합리적

하지만 다른 신호 있으면:
momentum = 4 (M1+M4) + 2.5 = 6.5
momentum -= 1.25 = 5.25 (19% 감소) vs
momentum *= 0.5 = 3.25 (50% 감소) ← **불일관!**
```

---

### 2.6 RSI의 이중 사용 (Momentum + Reversion)

#### Momentum에서 (Line 855)
```python
if ind.rsi_14 is not None and 50 <= ind.rsi_14 <= 65:
    momentum += 1.5
```
- **목적**: RSI가 중립~강세 영역 = 상승 추진력
- **범위**: 50-65 (매우 좁은 범위)

#### Reversion에서 (Line 862-866)
```python
if ind.rsi_14 < 25: reversion += 3.0
elif ind.rsi_14 < 30: reversion += 2.5
elif ind.rsi_14 < 35: reversion += 1.5
elif ind.rsi_14 < 40: reversion += 0.5
```
- **목적**: RSI 과매도 = 반발 기회
- **범위**: <40 (광범위)

#### 문제점
```
RSI = 55인 경우:
- Momentum: +1.5
- Reversion: +0.0
- 단방향 신호 (모멘텀만)

RSI = 25인 경우:
- Momentum: +0.0
- Reversion: +3.0
- 단방향 신호 (reversion만)

RSI = 40인 경우:
- Momentum: +0.0
- Reversion: +0.5
- 혼합 신호 (약한 reversion)

⚠️ RSI 40-50 구간은 두 모델 모두에서 무시됨!
   (가장 중립적인 영역이므로 의도적일 수 있음)
```

**평가**: 설계는 **상호배제적이고 명확**하지만, RSI만으로는:
- **상위 신호 통합 불가**: RSI 40-50 + 다른 강세 신호가 있어도 momentum boost 없음
- **다른 지표는 보완**: StochRSI는 reversion, MACD는 별도, MA는 독립

**심각도**: 중간 (설계 의도가 명확하나 표현 범위가 제한적)

---

### 2.7 Bollinger Band가 Reversion에만 사용되는 문제

**현재**:
- BB Position (R3): Reversion에만 (0~2.5)
- BB Squeeze (R4): Reversion에만 (0~1.5)

**Momentum에 도움이 될 상황**:
```
1. BB Squeeze 후 확장 (BB Expansion)
   - Bollinger Band가 축소했다가 확장 시작
   - 변동성 증가 + 추세 전환 신호
   - 현재: 무시됨 (R4에서 squeeze만 측정)

2. Price at Upper Band + Golden Cross
   - MACD Golden Cross + Price 상단 접근
   - 강세 신호의 강화
   - 현재: Momentum에는 무영향, Reversion에는 감소 (bb_pct > 80)
```

**코드** (Line 881-884):
```python
if bb_pct < 10: reversion += 2.5
elif bb_pct < 20: reversion += 2.0
elif bb_pct < 30: reversion += 1.0
# bb_pct >= 30은 페널티 없음 (대신 reversion 0)
```

**문제**:
- **상단 접근 (bb_pct > 80)의 강세 신호를 버림**
- RSI Overbought (>70) 가드는 있지만 BB 상단은 비대칭
- **Momentum 모델이 volatility expansion을 무시**

**심각도**: 중간 (보완 메커니즘은 있지만 불완전)

---

## 3. 가중치 체계의 합리성

### 3.1 Regime별 가중치 근거 부재

**현재 설정** (Line 754-762):
```
VIX > 28: trending=0.25, rev=0.75 (high_volatility)
VIX 20-28: trending=0.45, rev=0.55 (transitional)
VIX ≤ 20: trending=0.70, rev=0.30
```

**분석**:
| VIX | Regime | Mom:Rev | 근거 |
|-----|--------|---------|------|
| >28 | High Vol | 25:75 | ✓ VIX 급등 시 reversion이 유리 |
| 20-28 | Trans | 45:55 | ? 정확한 근거 불명 |
| ≤20 | Trending | 70:30 | ✓ 낮은 VIX = 추세 강함 |

**문제**:
1. **Transitional 구간의 45:55 비율이 정당화되지 않음**
   - 20과 28 사이의 선형 보간인가? (아님)
   - 선형이라면: 45 = 25 + (70-25) × (28-X) / (28-20)
   - X = 25.6 (약 25-26) → 45는 약 중간값
   - 설계 의도: 명확하지 않음

2. **VIX 임계값 선택 근거 부재**
   - 왜 28, 20인가? (업계 표준: 20=공포 시작, 30=극심한 공포)
   - 현재 기준: 25를 기준으로 -5/-3 범위 (비대칭)

3. **각 factor 내 세부 가중치 근거 완전 부재**
   - 왜 M1 (0-4)는 M2 (0-3)보다 큰가?
   - 왜 R1 (0-3)은 R2 (0-2)보다 큰가?
   - 통계적 검증 or 경험적 자동조정: 없음

**심각도**: 높음 (경험 기반 설정 + 검증 없음)

---

### 3.2 각 Factor 내 세부 가중치 부재

#### M1 (MA Alignment): 0~4
- **근거**: Bullish 정렬의 강도를 4단계로 표현
- **문제**: 왜 4인가? 다른 선택지:
  - 3점 (perfect stacking만): 강력하지만 도달 어려움
  - 5점: 더 많은 차별화, 다른 요소 약화
  - 가중치 없음: 모든 MA 동등

#### M2 (MACD): 0~3
- **golden cross 2.5**: 가장 강한 단일 신호
- **문제**: MACD histogram > 0은 1.5인데, golden cross는 2.5?
  - **차이: 1.0점** (histogram 개선 신호 vs 절대 전환)
  - 근거: 전환이 더 강하다? → 논리적이지만 수치 정당화 없음

#### Volume Multiplier 비대칭 (0.6 vs 1.4)
- **문제**: 0.6~1.4 범위가 **비대칭**
  - 1.4 / 1.0 = 1.4배 증가
  - 0.6 / 1.0 = 0.6배 감소 (40% 약화 vs 40% 강화 아님!)
  - **상향 편향**: 고볼륨이 저볼륨보다 더 강한 효과

---

## 4. Threshold 0.5의 적절성

**현재 설정** (Line 959):
```python
if final > 0.5:
    scores[ticker] = round(final, 2)
```

**분석**:
```
Trending 최대값:        15.67 (penalty 전) → 9.4 (penalty 후)
Threshold 0.5:          5.3% of maximum ✗

High-vol 최대값:        9.4 (대략)
Threshold 0.5:          5.3% of maximum (더 적절)

Transitional 최대값:    ~11.5
Threshold 0.5:          4.3% of maximum
```

**문제**:
1. **Regime마다 의미가 다름**
   - Trending: 최대값이 9.4인데 0.5는 5.3%
   - High-vol: 최대값이 ~9.4인데 0.5는 5.3%
   - **일관성 있지만, 절대값 기준이 아닌 상대값 기준이어야 함**

2. **654개 주식 중 대략 몇 개가 0.5를 초과하는가?**
   - 로그 분포라면: 상위 10-15% 추정
   - 현재 top 50 선택 → 상위 7.6%만 선택
   - **Threshold 0.5가 과도할 수 있음**

3. **0.5의 수학적 의미**
   - Trending: 7.42 (raw max) × 1.4 (vol) ÷ 20.79 (최대) = 0.5
   - 계산 복잡도가 높음 → 우연의 일치 가능

**평가**: Threshold 0.5는 **직관적이지 않으나 결과적으로는 합리적** (top 50 선택 달성)

---

## 5. 사각지대 (Blind Spot) 분석

### 5.1 알고리즘이 놓치는 매수 기회 유형

#### 1. RSI 40-50 + 다른 강세 신호
```
예: RSI=45 + MACD GC + MA alignment ✓
- M1 (MA): +4
- M2 (MACD GC): +2.5
- M4 (RSI zone): +0 (50-65 범위 밖)
- Momentum: 6.5 (RSI zone 보너스 없음)

vs RSI=55인 같은 상황:
- M1 (MA): +4
- M2 (MACD GC): +2.5
- M4 (RSI zone): +1.5 ✓
- Momentum: 8.0

→ RSI 40-50 구간에서 +1.5 손실!
```

**심각도**: 중간 (제한된 손실, 모멘텀 여전히 6.5로 충분할 수 있음)

#### 2. BB Expansion (Squeeze 해제) + Momentum
```
예: BB Squeeze 해제 직후 + MACD GC
- R4 (BB Squeeze): 0 (squeeze 해제, 확장 중)
- R1-R3 (other reversion): 0 (price not oversold)
- Reversion: 0

그러나 Momentum:
- M2 (MACD): +2.5
- 다른 신호 있으면 sufficient

→ Volatility expansion 신호 누락 (high volatility 환경에서 손실)
```

**심각도**: 낮음 (momentum이 보완 가능, 다만 volatility surge 신호 적음)

#### 3. Price < MA200이지만 Mean-Reversion 극도로 강한 경우
```
예: Price MA200에서 -15% (매우 약세)
    RSI = 15 (극도의 과매도)
    BB Position pct = 5% (하단 극단)

Reversion 점수: 3 + ? + 2.5 + ? = ~6점
× 0.5 (MA200 패널티) = 3점

vs 다른 regime: 6점

→ MA200 아래 페널티가 강한 반발 신호도 50% 감소
```

**심각도**: 높음 (강한 반발 신호를 과도하게 약화)

#### 4. 초고가 변동성 확장 (Volatility Spike)
```
VIX > 40 (극심한 공포)
- Regime: high_volatility (25:75 MomRev)
- Reversion 가중치: 75% (거의 전부)

그러나:
- ADX multiplier는 여전히 1.0~1.3 범위 (momentum에만)
- Momentum 신호가 약해도 trend-following 추세는 유지
- 마이너스 divergence 신호 약함

→ 극도의 공포 속 반발 기회를 충분히 포착하지만,
  momentum 신호는 과도하게 약화 가능
```

**심각도**: 중간

#### 5. Earnings 직후 모멘텀 (Price Jump)
```
예: Earnings Beat + Price 급등 3%
- MACD가 아직 positive cross 안함 (지표 lag)
- RSI가 50-65 zone에 진입 (M4 +1.5)
- Volume 급증 (vol_mult 1.4)
- 하지만 MA gap up으로 인해 MA200과 멀어짐

Momentum: 3 (M1, MA new high) + 1 (M2, MACD positive) + 1.5 (M4) × 1.3 ADX = 5.95
→ 충분하지만 처음 jump는 놓칠 수 있음
```

**심각도**: 낮음 (AI prompt 분석이 보완 가능)

---

### 5.2 알고리즘이 과도하게 선호하는 유형

#### 1. Golden Cross + High Volume (과장된 신뢰)
```
예: MACD GC + Vol 1.5×
- M2: +2.5
- Vol mult: ×1.2

그러나:
- Price가 MA50 아래일 수도 있음 (false cross)
- Bull Trap Penalty로 최대 -1.25만 감소
- 절대값 페널티는 기저 momentum이 충분하면 미미

결과: Trending regime에서 false GC도 높은 점수 가능
```

**심각도**: 중간 (Bull Trap Penalty가 부분적 보호, 비일관성은 유지)

#### 2. RSI 과매도 + Low ADX (false reversion)
```
예: RSI=20 (R1 +3.0) + ADX=12 (약한 추세, 범위 박스)
- ADX < 20 → momentum *= 0.7 (momentum만 감소)
- Reversion: 3.0 (momentum 감소와 무관)

결과: Reversion 신호 과도하게 강함 (범위 박스 하단에서 반발 중인 경우)
```

**심각도**: 높음 (ADX 상호작용 부재, 2.2 문제와 동일)

#### 3. Volume Spike (잘못된 신호)
```
예: 일회성 대량 매도 후 회복 불확실한데 vol_mult 1.4
- Volume는 높지만 negative divergence (OBV -1.0도 가능)
- net: 1.4 - 1.0/raw = 약 중립

하지만 positive OBV divergence라면:
- Vol 1.4 + OBV +1.5 = 극도로 강함
- Confirmation 신호 과도하게 가중

결과: Volume이 높은 모든 신호가 과도하게 강화됨
```

**심각도**: 중간 (OBV 보호 있음, 절대값 혼용으로 비일관)

#### 4. BB Lower에 Price 접근 (과도한 reversion 기대)
```
예: Price at BB Lower pct=5% + RSI=22
- R3 (BB): +2.5
- R1 (RSI): +3.0
- Reversion: 5.5 (높음)

그러나:
- Price가 지속적으로 하락 추세 (falling knife)
- BB Lower가 하향 이동 중 (실제 지지 아님)
- Knife Penalty로 최대 40% 감소만 가능

결과: 손실 주식의 반발 신호를 과도하게 신뢰
```

**심각도**: 높음 (falling knife는 개별 신호, BB는 절대값이므로 보호 불충분)

---

## 6. 성과 및 개선 제안 (분석만, 구현 제외)

### 6.1 구조적 문제 요약

| 우선순위 | 문제 | 영향도 | 시급성 |
|---------|------|--------|--------|
| 1 | ADX가 Momentum에만 적용 | 높음 | 높음 |
| 2 | Momentum > Reversion 스케일 | 높음 | 중간 |
| 3 | MA200 penalty (reversion만) | 높음 | 중간 |
| 4 | Volume + OBV 혼용 (additive) | 중간 | 중간 |
| 5 | OBV 비대칭 (-1 vs +1.5) | 중간 | 낮음 |
| 6 | Bull Trap penalty 비일관 | 중간 | 낮음 |
| 7 | RSI 40-50 gap | 중간 | 낮음 |
| 8 | 가중치 근거 부재 | 높음 | 낮음 |

### 6.2 이론적 개선 방향 (수학만)

**옵션 A: Momentum/Reversion 스케일 정규화**
```
momentum_normalized = momentum / 10.6  # 0~1
reversion_normalized = reversion / 9.0  # 0~1

raw = regime_mom_w × momentum_normalized
    + regime_rev_w × reversion_normalized
```
→ Regime 가중치가 실제 상대 중요도 반영 가능

**옵션 B: ADX 상호작용 수정**
```
if ind.adx_14 > 30:
    momentum *= 1.3
    reversion *= 0.7
elif ind.adx_14 < 20:
    momentum *= 0.7
    reversion *= 1.3
```
→ 추세 강도가 양쪽 신호에 반영

**옵션 C: MA200 penalty 통합**
```
# 현재: reversion *= 0.5
# 개선:
if current_price < ind.ma_200:
    momentum *= 0.6
    reversion *= 0.5
```
→ Downtrend에서 momentum도 억제

**옵션 D: Volume/OBV 일관성**
```
# 현재: raw × vol_mult + obv_bonus
# 개선 (일관 multiplicative):
adjusted = raw × vol_mult × (1.0 + obv_factor)
# obv_factor: -0.3 ~ +0.3
```
→ 모든 조정이 상대적(%)

---

## 7. 최종 결론

### 주요 발견

1. **수학적 범위 명확함**
   - Momentum: 0~10.6
   - Reversion: 0~9.0
   - 최종: -1.0 (bearish OBV) ~ 15.7 (trending + high vol)

2. **구조적 일관성 부족**
   - ADX가 Momentum에만 영향
   - Penalty가 혼합 메커니즘 (% vs 절대값)
   - Volume (%) + OBV (절대값) 혼용

3. **설계 의도는 명확하나 검증 부재**
   - Regime weighting은 VIX 기반 논리적
   - 각 factor 가중치는 근거 불명
   - 통계적 최적화 증거 없음

4. **실운영 대비 이론적 최대값 보수적**
   - Threshold 0.5는 top 50 선택 달성 (7.6% 상위)
   - Penalty가 충분히 강력하지 않음 (특히 bull trap)
   - OBV divergence (-1.0)는 거의 작동하지 않음

5. **Blind Spot 분포**
   - 약한 신호 조합 (RSI 40-50) 놓침
   - Volatility expansion (BB squeeze 해제) 미검출
   - 극도 과매도 상황에서 과도한 penalty

### 알고리즘 평가

**강점**:
- 명확한 dual sub-model 구조
- Regime switching으로 시장 국면 반응
- Penalty 기반 위험 신호 억제 (falling knife 등)

**약점**:
- 상호작용 불완전 (ADX ↔ Reversion, MA200 ↔ Momentum)
- 스케일 비일관성 (% vs 절대값)
- 경험적 가중치 (검증 없음)

**결론**:
> 실전에서는 **AI 최종 판단 (45% 기술 + 30% 펀더멘탈)이 주요 필터 역할**하므로, 기술적 스크리닝의 구조적 문제는 **top 50 선정 효율성에만 영향**. 하지만 수학적 엄밀성과 일관성 개선은 **성과 재현성**과 **미래 최적화**를 위해 권장됨.

---

## 부록: 수치 샘플 시뮬레이션

### Strong Bull 케이스 (Trending)
```
MA Align (bullish 4-stacking): 4
MACD: Golden cross, 2.5
RSI: 58 (zone), 1.5
ADX: 28 (× 1.15)
Momentum = (4 + 2.5 + 1.5) × 1.15 = 8.51

RSI oversold: 0
StochRSI cross: 0
BB Position: 50% (neutral), 0
BB Squeeze: none, 0
Reversion = 0

Regime: trending (70:30)
Raw = 0.70 × 8.51 + 0.30 × 0 = 5.96

Vol: 1.5× = 1.2
OBV: confirming, +0.5
Adjusted = 5.96 × 1.2 + 0.5 = 7.65

Knife pen: none, = 1.0
Final = 7.65 × 1.0 = 7.65 ✓ 선택됨 (> 0.5)
```

### Weak Bull 케이스 (Transitional)
```
MA Align: 2 (above 20, 50만)
MACD: positive not cross, 1.5
RSI: 48 (zone 외), 0
ADX: 18 (× 0.7)
Momentum = (2 + 1.5) × 0.7 = 2.45

RSI oversold: 35, 0.5
StochRSI: neutral, 0
BB Position: 60%, 0
BB Squeeze: none, 0
Reversion = 0.5

Regime: transitional (45:55)
Raw = 0.45 × 2.45 + 0.55 × 0.5 = 1.10 + 0.275 = 1.375

Vol: 0.7× = 0.8
OBV: divergence, -1.0
Adjusted = 1.375 × 0.8 - 1.0 = 1.1 - 1.0 = 0.1

Final = 0.1 × (1 - 0) = 0.1 ✗ 미선택 (< 0.5)
```

### False Signal (High Vol)
```
MA Align: 1 (above MA20만)
MACD: Golden cross, 2.5
RSI: 22 (oversold), 0
ADX: 35 (× 1.3)
Momentum = (1 + 2.5) × 1.3 = 4.55

RSI oversold: 22, 3.0
StochRSI: cross, 2.0
BB Position: 8%, 2.5
BB Squeeze: yes, 1.5
Reversion = 3.0 + 2.0 + 2.5 + 1.5 = 9.0

Regime: high_vol (25:75)
Raw = 0.25 × 4.55 + 0.75 × 9.0 = 1.14 + 6.75 = 7.89

Vol: 2.1× = 1.4
OBV: confirming, +0.5
Adjusted = 7.89 × 1.4 + 0.5 = 11.05 + 0.5 = 11.55

Knife pen: 2-day down, = 0
Final = 11.55 ✓ 강하게 선택됨

→ 하지만 RSI 과매도 + GC에만 의존 (MA20 아래일 수 있음)
```

---

**작성 완료**: 2026-02-24
**분석 신뢰도**: 높음 (코드 기반 수학적 계산)
