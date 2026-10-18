export interface PatternPoint {
  key: string;
  index: number;
  high: number;
  low: number;
  close: number;
}

export interface TrendLine {
  kind: "support" | "resistance";
  startKey: string;
  endKey: string;
  startIndex: number;
  endIndex: number;
  startValue: number;
  endValue: number;
  currentValue: number;
}

export interface ChartPatternAnalysis {
  label: string;
  bias: "LONG" | "SHORT" | "WAIT";
  supportLine: TrendLine | null;
  resistanceLine: TrendLine | null;
  support: number | null;
  resistance: number | null;
  explanation: string;
  nextAction: string;
}

interface CandleLike {
  key: string;
  high: number;
  low: number;
  close: number;
}

const MIN_SWINGS = 2;

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function lineValue(a: PatternPoint, b: PatternPoint, index: number): number {
  if (a.index === b.index) return b.close;
  const slope = (b.close - a.close) / (b.index - a.index);
  return a.close + slope * (index - a.index);
}

function trendLine(kind: TrendLine["kind"], a: PatternPoint, b: PatternPoint, currentIndex: number): TrendLine {
  return {
    kind,
    startKey: a.key,
    endKey: b.key,
    startIndex: a.index,
    endIndex: b.index,
    startValue: round(a.close),
    endValue: round(b.close),
    currentValue: round(lineValue(a, b, currentIndex)),
  };
}

function findSwings(data: CandleLike[], window: number): { highs: PatternPoint[]; lows: PatternPoint[] } {
  const highs: PatternPoint[] = [];
  const lows: PatternPoint[] = [];
  for (let i = window; i < data.length - window; i++) {
    const slice = data.slice(i - window, i + window + 1);
    const candle = data[i];
    const maxHigh = Math.max(...slice.map((d) => d.high));
    const minLow = Math.min(...slice.map((d) => d.low));
    if (candle.high >= maxHigh) {
      highs.push({ key: candle.key, index: i, high: candle.high, low: candle.low, close: candle.high });
    }
    if (candle.low <= minLow) {
      lows.push({ key: candle.key, index: i, high: candle.high, low: candle.low, close: candle.low });
    }
  }
  return { highs, lows };
}

function recentPair(points: PatternPoint[]): [PatternPoint, PatternPoint] | null {
  if (points.length < MIN_SWINGS) return null;
  const recent = points.slice(-5);
  return [recent[recent.length - 2], recent[recent.length - 1]];
}

export function analyseChartPattern(input: CandleLike[]): ChartPatternAnalysis {
  const data = input.filter((d) => Number.isFinite(d.high) && Number.isFinite(d.low) && Number.isFinite(d.close));
  const fallback: ChartPatternAnalysis = {
    label: "No clear pattern",
    bias: "WAIT",
    supportLine: null,
    resistanceLine: null,
    support: null,
    resistance: null,
    explanation: "Not enough clean candles to draw reliable analyst-style trendlines.",
    nextAction: "Wait for more candles or use only horizontal support and resistance.",
  };
  if (data.length < 12) return fallback;

  const last = data[data.length - 1];
  const currentIndex = data.length - 1;
  const swingWindow = data.length >= 80 ? 3 : 2;
  const { highs, lows } = findSwings(data, swingWindow);
  const lowPair = recentPair(lows);
  const highPair = recentPair(highs);
  const supportLine = lowPair ? trendLine("support", lowPair[0], lowPair[1], currentIndex) : null;
  const resistanceLine = highPair ? trendLine("resistance", highPair[0], highPair[1], currentIndex) : null;
  const support = round(Math.min(...data.slice(-20).map((d) => d.low)));
  const resistance = round(Math.max(...data.slice(-20).map((d) => d.high)));

  const higherLows = Boolean(lowPair && lowPair[1].close > lowPair[0].close);
  const lowerLows = Boolean(lowPair && lowPair[1].close < lowPair[0].close);
  const higherHighs = Boolean(highPair && highPair[1].close > highPair[0].close);
  const lowerHighs = Boolean(highPair && highPair[1].close < highPair[0].close);
  const rangePct = resistance > 0 ? ((resistance - support) / resistance) * 100 : 0;
  const brokeResistance = resistanceLine ? last.close > resistanceLine.currentValue * 1.002 : last.close > resistance * 1.002;
  const brokeSupport = supportLine ? last.close < supportLine.currentValue * 0.998 : last.close < support * 0.998;

  let label = "Range / consolidation";
  let bias: ChartPatternAnalysis["bias"] = "WAIT";
  let explanation = `Price is between support ${support} and resistance ${resistance}.`;
  let nextAction = "Wait for a close outside the range, or trade only near the edges with strict invalidation.";

  if (higherLows && higherHighs) {
    label = "Rising channel";
    bias = "LONG";
    explanation = "Swing lows and swing highs are stepping higher, so buyers are defending pullbacks.";
    nextAction = supportLine
      ? `Look for continuation while price holds the rising support near ${supportLine.currentValue}. A close below it weakens the pattern.`
      : "Look for continuation while price keeps making higher lows.";
  } else if (lowerLows && lowerHighs) {
    label = "Falling channel";
    bias = "SHORT";
    explanation = "Swing highs and swing lows are stepping lower, so rallies are being sold.";
    nextAction = resistanceLine
      ? `Avoid long bias until price reclaims falling resistance near ${resistanceLine.currentValue}. A rejection keeps downside pressure active.`
      : "Avoid long bias until price stops making lower highs.";
  } else if (higherLows && lowerHighs) {
    label = "Triangle compression";
    bias = "WAIT";
    explanation = "Higher lows and lower highs show compression; direction is not confirmed yet.";
    nextAction = `Wait for a candle close above resistance ${resistance} or below support ${support}.`;
  } else if (higherLows && !higherHighs) {
    label = "Ascending pressure";
    bias = "LONG";
    explanation = "Higher lows are pressing into overhead resistance.";
    nextAction = `Breakout confirmation needs a close above ${resistance}; failure below ${support} cancels the setup.`;
  } else if (lowerHighs && !lowerLows) {
    label = "Descending pressure";
    bias = "SHORT";
    explanation = "Lower highs are pressing into support.";
    nextAction = `Breakdown confirmation needs a close below ${support}; reclaim above ${resistance} cancels the setup.`;
  } else if (rangePct <= 3.5) {
    label = "Tight range";
    bias = "WAIT";
    explanation = `Price is compressed inside a ${round(rangePct)}% range.`;
    nextAction = `Wait for expansion through ${resistance} or ${support}.`;
  }

  if (brokeResistance) {
    label = `${label} breakout`;
    bias = "LONG";
    explanation = `${explanation} Latest close is above the active resistance line or range high.`;
    nextAction = supportLine
      ? `Next step is a hold or retest above the breakout area. Invalidate if price closes back below ${supportLine.currentValue}.`
      : `Next step is a hold above ${resistance}. Invalidate if price closes back inside the range.`;
  } else if (brokeSupport) {
    label = `${label} breakdown`;
    bias = "SHORT";
    explanation = `${explanation} Latest close is below the active support line or range low.`;
    nextAction = resistanceLine
      ? `Next step is follow-through or a failed retest. Invalidate bearish read if price reclaims ${resistanceLine.currentValue}.`
      : `Next step is follow-through below ${support}. Invalidate bearish read if price closes back inside the range.`;
  }

  return {
    label,
    bias,
    supportLine,
    resistanceLine,
    support,
    resistance,
    explanation,
    nextAction,
  };
}
