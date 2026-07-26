/**
 * Bibliothèque de composants de Metric.
 *
 * Tout écran importe d'ici, jamais d'un module de composant en particulier : c'est ce
 * qui permet de déplacer ou de découper un composant sans toucher aux écrans.
 */

export { Chart } from './Chart';
export type { BandSeries, ChartProps, Series } from './Chart';

export { Heatmap } from './Heatmap';
export type { DayState, HeatDay, HeatWeek, HeatmapProps, WeekStatus } from './Heatmap';

export { Toaster } from './Toaster';

export {
  AiBlock,
  Badge,
  Button,
  Card,
  CardHead,
  Empty,
  Eyebrow,
  Field,
  LogButton,
  Rule,
  Segmented,
} from './primitives';
export type { ButtonVariant, SegmentedOption, Tone } from './primitives';

export { Bars, Check, CheckGroup, Progress, Ring, Sparkline, Stat, Table } from './data';
export type { BarRow, Column } from './data';
