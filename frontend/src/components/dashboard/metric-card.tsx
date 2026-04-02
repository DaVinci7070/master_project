'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import Link from 'next/link'

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  trend?: 'up' | 'down' | 'neutral'
  href?: string
  className?: string
}

export function MetricCard({ title, value, subtitle, trend, href, className }: MetricCardProps) {
  const content = (
    <Card className={`${className} ${href ? 'cursor-pointer hover:bg-gray-50 transition-colors' : ''}`}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-gray-500">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold">{value}</span>
          {trend && (
            <span className={`text-sm ${
              trend === 'up' ? 'text-green-600' :
              trend === 'down' ? 'text-red-600' :
              'text-gray-500'
            }`}>
              {trend === 'up' ? '+' : trend === 'down' ? '-' : ''}
            </span>
          )}
        </div>
        {subtitle && <p className="text-sm text-gray-500 mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )

  if (href) {
    return <Link href={href}>{content}</Link>
  }
  return content
}
