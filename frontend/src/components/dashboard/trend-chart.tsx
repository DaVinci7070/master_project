'use client'

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface TrendChartProps {
  data: Array<{ execution: number; value: number }>
  title: string
  dataKey?: string
  color?: string
  yAxisLabel?: string
}

export function TrendChart({
  data,
  title,
  dataKey = 'value',
  color = '#6366f1',
  yAxisLabel
}: TrendChartProps) {
  return (
    <div className="w-full">
      <h3 className="text-sm font-medium text-gray-700 mb-3">{title}</h3>
      <div className="h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="execution"
              tick={{ fontSize: 12 }}
              label={{ value: 'Execution #', position: 'insideBottom', offset: -5, fontSize: 12 }}
            />
            <YAxis
              tick={{ fontSize: 12 }}
              label={yAxisLabel ? { value: yAxisLabel, angle: -90, position: 'insideLeft', fontSize: 12 } : undefined}
            />
            <Tooltip
              contentStyle={{ fontSize: 12 }}
              labelFormatter={(value) => `Execution #${value}`}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              name={title}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
