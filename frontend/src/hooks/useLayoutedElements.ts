'use client'

import { useCallback, useEffect, useState } from 'react'
import ELK from 'elkjs/lib/elk.bundled.js'
import type { Node, Edge } from '@xyflow/react'

const elk = new ELK()

interface LayoutOptions {
  direction?: 'DOWN' | 'RIGHT' | 'LEFT' | 'UP'
  nodeSpacing?: number
  layerSpacing?: number
}

const defaultOptions: LayoutOptions = {
  direction: 'DOWN',
  nodeSpacing: 150,  // Increased horizontal spacing
  layerSpacing: 150, // Increased vertical spacing between layers
}

export function useLayoutedElements<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  edges: Edge[],
  options: LayoutOptions = {}
) {
  const [layoutedNodes, setLayoutedNodes] = useState<Node<T>[]>([])
  const [layoutedEdges, setLayoutedEdges] = useState<Edge[]>([])
  const [isLayouting, setIsLayouting] = useState(false)

  const opts = { ...defaultOptions, ...options }

  const getLayoutedElements = useCallback(async () => {
    if (nodes.length === 0) {
      setLayoutedNodes([])
      setLayoutedEdges([])
      return
    }

    setIsLayouting(true)

    try {
      const direction = opts.direction ?? 'DOWN'
      const graph = {
        id: 'root',
        layoutOptions: {
          'elk.algorithm': 'layered',
          'elk.direction': direction,
          'elk.spacing.nodeNode': String(opts.nodeSpacing),
          'elk.spacing.componentComponent': String(opts.nodeSpacing),
          'elk.layered.spacing.baseValue': String(opts.layerSpacing),
          'elk.layered.spacing.nodeNodeBetweenLayers': String(opts.layerSpacing),
          'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
          // Better handling of disconnected components
          'elk.separateConnectedComponents': 'true',
          'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
          // Spread out nodes in same layer
          'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
          'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        },
        children: nodes.map((node) => ({
          id: node.id,
          width: node.width || 200,
          height: node.height || 90,
        })),
        edges: edges.map((edge) => ({
          id: edge.id,
          sources: [edge.source],
          targets: [edge.target],
        })),
      }

      const layoutedGraph = await elk.layout(graph)

      const newNodes = nodes.map((node) => {
        const layoutedNode = layoutedGraph.children?.find((n) => n.id === node.id)
        return {
          ...node,
          position: {
            x: layoutedNode?.x ?? 0,
            y: layoutedNode?.y ?? 0,
          },
        }
      })

      setLayoutedNodes(newNodes)
      setLayoutedEdges(edges)
    } catch (error) {
      console.error('Layout failed:', error)
      // Fall back to improved grid layout with more spacing
      const gridCols = Math.min(4, Math.ceil(Math.sqrt(nodes.length)))
      const nodeWidth = 250
      const nodeHeight = 150
      const gridNodes = nodes.map((node, i) => ({
        ...node,
        position: {
          x: (i % gridCols) * nodeWidth,
          y: Math.floor(i / gridCols) * nodeHeight,
        },
      }))
      setLayoutedNodes(gridNodes)
      setLayoutedEdges(edges)
    } finally {
      setIsLayouting(false)
    }
  }, [nodes, edges, opts.direction, opts.nodeSpacing, opts.layerSpacing])

  useEffect(() => {
    getLayoutedElements()
  }, [getLayoutedElements])

  return {
    nodes: layoutedNodes,
    edges: layoutedEdges,
    isLayouting,
    recalculate: getLayoutedElements,
  }
}
