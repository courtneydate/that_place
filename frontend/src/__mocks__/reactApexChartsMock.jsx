/* eslint-disable */
/** Lightweight ApexCharts stub for Jest / jsdom. */
const ReactApexChart = ({ type, series, height }) => (
  <div
    data-testid="apex-chart"
    data-type={type}
    data-height={height}
    data-series-count={series ? series.length : 0}
  />
);

export default ReactApexChart;
