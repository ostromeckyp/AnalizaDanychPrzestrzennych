import { AdvancedMargin, type AdvancedMarginProps } from './AdvancedMargin';
import { DraftField, type DraftFieldProps } from './DraftField';
import { LayersControl, type LayersControlProps } from './LayersControl';
import { LevelControl, type LevelControlProps } from './LevelControl';
import './panel.css';

export type ParameterPanelProps = {
  draft: DraftFieldProps;
  level: LevelControlProps;
  layers: LayersControlProps;
  margin: AdvancedMarginProps;
};

export function ParameterPanel({ draft, level, layers, margin }: ParameterPanelProps) {
  return (
    <div className="panel" role="region" aria-label="Parametry">
      <DraftField {...draft} />
      <LevelControl {...level} />
      <LayersControl {...layers} />
      <AdvancedMargin {...margin} />
    </div>
  );
}
