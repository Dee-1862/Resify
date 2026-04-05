import { useEffect, useRef, useState } from 'react';
import './KnowledgeGraph.css';

export interface NodeData {
    id: string;
    label: string;
    type: 'root' | 'agent' | 'finding' | 'contradiction' | 'claim';
    status: 'pending' | 'active' | 'complete' | 'error';
    x: number;
    y: number;
}

export interface EdgeData {
    source: string;
    target: string;
    active: boolean;
}

interface KnowledgeGraphProps {
    nodes: NodeData[];
    edges: EdgeData[];
}

const AGENT_META: Record<string, { code: string; desc: string }> = {
    'a1': { code: 'FET', desc: 'Paper fetch' },
    'a2': { code: 'EXT', desc: 'Citation parse' },
    'a3': { code: 'EXI', desc: 'DB lookup' },
    'a4': { code: 'EMB', desc: 'Embedding score' },
    'a5': { code: 'LLM', desc: 'Claim verify' },
    'a6': { code: 'SYN', desc: 'Report build' },
};

const STATUS_DESC: Record<string, string> = {
    pending:  'standby',
    active:   'processing…',
    complete: 'done',
    error:    'failed',
};

export function KnowledgeGraph({ nodes, edges }: KnowledgeGraphProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [dims, setDims] = useState({ w: 900, h: 380 });

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const update = () => setDims({ w: el.clientWidth, h: el.clientHeight });
        const ro = new ResizeObserver(update);
        ro.observe(el);
        update();
        return () => ro.disconnect();
    }, []);

    const pipelineNodes = nodes.filter(n => n.type === 'root' || n.type === 'agent');

    // Pixel position map
    const posMap = new Map<string, { x: number; y: number }>();
    pipelineNodes.forEach(n => {
        posMap.set(n.id, { x: (n.x / 100) * dims.w, y: (n.y / 100) * dims.h });
    });

    // Build edges with cubic bezier control points
    const edgeList = edges
        .filter(e => posMap.has(e.source) && posMap.has(e.target))
        .map(e => {
            const s = posMap.get(e.source)!;
            const t = posMap.get(e.target)!;
            const id = `${e.source}-${e.target}`;
            const dx = t.x - s.x;
            const dy = t.y - s.y;

            let d: string;
            if (Math.abs(dy) > 60) {
                // Diagonal bend: use a smooth S-curve
                const cpx1 = s.x + dx * 0.1;
                const cpy1 = s.y + dy * 0.55;
                const cpx2 = t.x - dx * 0.1;
                const cpy2 = t.y - dy * 0.35;
                d = `M ${s.x} ${s.y} C ${cpx1} ${cpy1} ${cpx2} ${cpy2} ${t.x} ${t.y}`;
            } else {
                // Horizontal: gentle arc upward
                const cx = s.x + dx * 0.5;
                const cy = s.y - Math.abs(dx) * 0.055;
                d = `M ${s.x} ${s.y} Q ${cx} ${cy} ${t.x} ${t.y}`;
            }

            return { id, d, active: e.active, source: e.source };
        });

    const activeCount = pipelineNodes.filter(n => n.status === 'active').length;
    const completeCount = pipelineNodes.filter(n => n.status === 'complete').length;
    const totalAgents = pipelineNodes.filter(n => n.type === 'agent').length;
    const allDone = completeCount > 0 && pipelineNodes.every(n => n.status === 'complete');

    // Progress 0–100 based on how many agents are done
    const progress = totalAgents > 0 ? Math.round((completeCount / (totalAgents + 1)) * 100) : 0;

    return (
        <div className="kg-wrap">

            {/* ── Top bar ── */}
            <div className="kg-head rule-bottom">
                <div className="kg-head-left">
                    <span className="label">Investigation Map</span>
                    {activeCount > 0 && (
                        <span className="kg-head-sub mono">{activeCount} agent{activeCount > 1 ? 's' : ''} running</span>
                    )}
                    {allDone && (
                        <span className="kg-head-sub mono kg-head-sub-done">pipeline complete</span>
                    )}
                </div>
                <div className="kg-head-right">
                    {/* Progress bar */}
                    <div className="kg-progress-track">
                        <div
                            className="kg-progress-fill"
                            style={{ width: `${allDone ? 100 : progress}%` }}
                        />
                    </div>
                    <span className="kg-progress-pct mono">{allDone ? 100 : progress}%</span>
                </div>
            </div>

            {/* ── Canvas ── */}
            <div className="kg-canvas" ref={containerRef}>

                {/* Active scan line */}
                {activeCount > 0 && <div className="kg-scanline" />}

                <svg className="kg-svg" width={dims.w} height={dims.h}>
                    <defs>
                        <marker id="kg-arr" markerWidth="8" markerHeight="6"
                            refX="7" refY="3" orient="auto">
                            <polygon points="0 0, 8 3, 0 6" fill="rgba(28,25,22,0.22)" />
                        </marker>
                        <marker id="kg-arr-on" markerWidth="8" markerHeight="6"
                            refX="7" refY="3" orient="auto">
                            <polygon points="0 0, 8 3, 0 6" fill="var(--ink)" />
                        </marker>
                        <marker id="kg-arr-done" markerWidth="8" markerHeight="6"
                            refX="7" refY="3" orient="auto">
                            <polygon points="0 0, 8 3, 0 6" fill="var(--verified)" />
                        </marker>
                        <filter id="kg-glow">
                            <feGaussianBlur stdDeviation="2.5" result="blur" />
                            <feComposite in="SourceGraphic" in2="blur" operator="over" />
                        </filter>
                    </defs>

                    {edgeList.map(e => {
                        const srcNode = pipelineNodes.find(n => n.id === e.source);
                        const isDone = srcNode?.status === 'complete';
                        return (
                            <g key={e.id}>
                                {/* Base edge */}
                                <path
                                    id={`kgp-${e.id}`}
                                    className={`kg-edge${e.active ? ' kg-edge-on' : isDone ? ' kg-edge-done' : ''}`}
                                    d={e.d}
                                    markerEnd={e.active ? 'url(#kg-arr-on)' : isDone ? 'url(#kg-arr-done)' : 'url(#kg-arr)'}
                                />

                                {/* Glow trace on active edge */}
                                {e.active && (
                                    <path
                                        className="kg-edge-glow"
                                        d={e.d}
                                        filter="url(#kg-glow)"
                                    />
                                )}

                                {/* Three-dot flow train on active edges */}
                                {e.active && [0, 0.3, 0.58].map((delay, i) => (
                                    <circle key={i} className={`kg-p kg-p-${i}`} r={3.5 - i * 0.8}>
                                        <animateMotion
                                            dur="1.0s"
                                            repeatCount="indefinite"
                                            begin={`${delay}s`}
                                            calcMode="spline"
                                            keySplines="0.4 0 0.6 1"
                                        >
                                            <mpath href={`#kgp-${e.id}`} />
                                        </animateMotion>
                                    </circle>
                                ))}
                            </g>
                        );
                    })}
                </svg>

                {/* Pipeline nodes */}
                {pipelineNodes.map(node => {
                    const pos = posMap.get(node.id);
                    if (!pos) return null;
                    const meta = AGENT_META[node.id];

                    return (
                        <div
                            key={node.id}
                            className={`kg-node kg-nt-${node.type} kg-ns-${node.status}`}
                            style={{ left: pos.x, top: pos.y }}
                        >
                            {/* Active halo */}
                            {node.status === 'active' && (
                                <>
                                    <div className="kg-halo kg-halo-1" />
                                    <div className="kg-halo kg-halo-2" />
                                </>
                            )}

                            <div className="kg-node-body">
                                {/* Agent code badge */}
                                {meta && (
                                    <div className="kg-code">{meta.code}</div>
                                )}

                                <div className="kg-node-text">
                                    <div className="kg-label">{node.label}</div>
                                    {meta && (
                                        <div className={`kg-desc kg-desc-${node.status}`}>
                                            {node.status === 'active'
                                                ? meta.desc
                                                : STATUS_DESC[node.status]}
                                        </div>
                                    )}
                                </div>

                                {/* Complete tick */}
                                {node.status === 'complete' && (
                                    <div className="kg-tick">✓</div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* ── Legend ── */}
            <div className="kg-legend rule-top">
                <div className="kg-leg-item"><span className="kg-ldot kg-ldot-root" /><span className="label">Root Query</span></div>
                <div className="kg-leg-item"><span className="kg-ldot kg-ldot-pending" /><span className="label">Pending</span></div>
                <div className="kg-leg-item"><span className="kg-ldot kg-ldot-active" /><span className="label">Active</span></div>
                <div className="kg-leg-item"><span className="kg-ldot kg-ldot-done" /><span className="label">Complete</span></div>
            </div>
        </div>
    );
}
