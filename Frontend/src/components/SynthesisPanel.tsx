import './SynthesisPanel.css';
import { useState, useEffect, useCallback, useRef } from 'react';

interface CitationDetail {
    id: number;
    claim: string;
    reference: { authors?: string; title?: string; year?: number };
    existence_status: string;
    verification?: { verdict: string; confidence: number; evidence?: string; explanation?: string; method: string } | null;
    source_found?: { title?: string; authors?: string[]; year?: number; _source?: string } | null;
}

interface SynthesisData {
    trustScore: number;
    totalCitations: number;
    supported: number;
    contradicted: number;
    uncertain: number;
    notFound: number;
    metadataErrors: number;
    conclusion: string;
    citations: CitationDetail[];
    paperKey: string;
}

interface Override {
    verdict: string;
    notes: string;
}

type FilterMode = 'all' | 'supported' | 'contradicted' | 'uncertain' | 'not_found';

const VERDICT_OPTIONS = [
    { value: 'supported', label: 'Verified', cls: 'status-ok' },
    { value: 'contradicted', label: 'Conflict', cls: 'status-conflict' },
    { value: 'uncertain', label: 'Unclear', cls: 'status-uncertain' },
    { value: 'not_found', label: 'Not Found', cls: 'status-notfound' },
];

export function SynthesisPanel({ data }: { data: SynthesisData }) {
    const [filter, setFilter] = useState<FilterMode>('all');
    const [expanded, setExpanded] = useState<Set<number>>(new Set());
    const [overrides, setOverrides] = useState<Record<string, Override>>({});
    const [editingId, setEditingId] = useState<number | null>(null);

    // Drag state
    const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
    const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
    const cardRef = useRef<HTMLDivElement>(null);

    const onDragStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
        // Only drag from the header, ignore clicks on buttons/links
        if ((e.target as HTMLElement).closest('button,a')) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        const rect = cardRef.current?.getBoundingClientRect();
        dragRef.current = {
            startX: e.clientX,
            startY: e.clientY,
            origX: pos?.x ?? (rect ? rect.left : 0),
            origY: pos?.y ?? (rect ? rect.top : 0),
        };
    }, [pos]);

    const onDragMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
        if (!dragRef.current) return;
        const dx = e.clientX - dragRef.current.startX;
        const dy = e.clientY - dragRef.current.startY;
        setPos({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
    }, []);

    const onDragEnd = useCallback(() => {
        dragRef.current = null;
    }, []);

    // Load existing overrides for this paper
    useEffect(() => {
        if (!data.paperKey) return;
        fetch(`/api/overrides/${encodeURIComponent(data.paperKey)}`)
            .then(r => r.json())
            .then(setOverrides)
            .catch(() => {});
    }, [data.paperKey]);

    const saveOverride = useCallback(async (citId: number, verdict: string, notes: string) => {
        await fetch('/api/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_key: data.paperKey,
                citation_id: citId,
                verdict,
                notes,
            }),
        });
        setOverrides(prev => ({ ...prev, [String(citId)]: { verdict, notes } }));
        setEditingId(null);
    }, [data.paperKey]);

    const removeOverride = useCallback(async (citId: number) => {
        await fetch('/api/override', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_key: data.paperKey,
                citation_id: citId,
            }),
        });
        setOverrides(prev => {
            const next = { ...prev };
            delete next[String(citId)];
            return next;
        });
        setEditingId(null);
    }, [data.paperKey]);

    // Recompute counts with overrides applied
    const getEffectiveStatus = (c: CitationDetail) => {
        const ov = overrides[String(c.id)];
        if (ov) return ov.verdict;
        if (c.existence_status === 'not_found') return 'not_found';
        const v = c.verification?.verdict;
        if (v === 'supported') return 'supported';
        if (v === 'contradicted') return 'contradicted';
        return 'uncertain';
    };

    const counts = { supported: 0, contradicted: 0, uncertain: 0, not_found: 0 };
    for (const c of data.citations) {
        const s = getEffectiveStatus(c);
        if (s in counts) counts[s as keyof typeof counts]++;
    }

    const effectiveScore = counts.supported + counts.contradicted + counts.uncertain > 0
        ? Math.round((counts.supported / (counts.supported + counts.contradicted + counts.uncertain)) * 1000) / 10
        : 0;

    const verdict =
        effectiveScore >= 90 ? 'HIGH CONFIDENCE' :
            effectiveScore >= 70 ? 'REVIEW SUGGESTED' : 'NEEDS REVIEW';

    const verdictClass =
        effectiveScore >= 90 ? 'verdict-pass' :
            effectiveScore >= 70 ? 'verdict-caution' : 'verdict-fail';

    const filtered = data.citations.filter(c => {
        const s = getEffectiveStatus(c);
        if (filter === 'all') return true;
        return s === filter;
    });

    const toggle = (id: number, element: HTMLElement | null) => {
        setExpanded(prev => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
                if (element) {
                    setTimeout(() => {
                        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }, 50);
                }
            }
            return next;
        });
    };

    const cardStyle: React.CSSProperties = pos
        ? { position: 'fixed', left: pos.x, top: pos.y, margin: 0 }
        : {};

    return (
        <div className={`synthesis-overlay anim-fade-up${pos ? ' synthesis-overlay-free' : ''}`}>
            <div className="synthesis-card" ref={cardRef} style={cardStyle}>
                <div
                    className="synth-head rule-bottom synth-drag-handle"
                    onPointerDown={onDragStart}
                    onPointerMove={onDragMove}
                    onPointerUp={onDragEnd}
                    onPointerCancel={onDragEnd}
                >
                    <span className="label">Integrity Report</span>
                    <div className="synth-head-right">
                        <span className="synth-drag-hint mono">⠿ drag</span>
                        <span className="synth-ts mono">{new Date().toLocaleTimeString()}</span>
                    </div>
                </div>

                <div className={`synth-verdict ${verdictClass}`}>
                    <div className="verdict-score mono" title={`Verified: ${counts.supported} | Conflict: ${counts.contradicted} | Unclear: ${counts.uncertain}`}>{effectiveScore}</div>
                    <div className="verdict-right">
                        <div className="verdict-label" title="Score based on proportion of verified vs conflicting/unclear citations" style={{cursor: 'help'}}>Confidence Score ⓘ</div>
                        <div className={`verdict-flag ${verdictClass}`}>{verdict}</div>
                    </div>
                </div>

                <div className="synth-citations rule-top">
                    <div className="label" style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--rule)' }}>
                        Citation Audit
                        {Object.keys(overrides).length > 0 && (
                            <span className="override-count mono"> ({Object.keys(overrides).length} edited)</span>
                        )}
                    </div>
                    <div className="cit-grid cit-grid-5">
                        <button className={`cit-cell cit-cell-btn ${filter === 'all' ? 'cit-active' : ''}`} onClick={() => setFilter('all')}>
                            <div className="cit-num mono">{data.totalCitations}</div>
                            <div className="label">Total</div>
                        </button>
                        <button className={`cit-cell cit-cell-btn cit-ok ${filter === 'supported' ? 'cit-active' : ''}`} onClick={() => setFilter('supported')}>
                            <div className="cit-num mono">{counts.supported}</div>
                            <div className="label">Verified</div>
                        </button>
                        <button className={`cit-cell cit-cell-btn cit-warn ${filter === 'contradicted' ? 'cit-active' : ''}`} onClick={() => setFilter('contradicted')}>
                            <div className="cit-num mono">{counts.contradicted}</div>
                            <div className="label">Conflict</div>
                        </button>
                        <button className={`cit-cell cit-cell-btn cit-uncertain ${filter === 'uncertain' ? 'cit-active' : ''}`} onClick={() => setFilter('uncertain')}>
                            <div className="cit-num mono">{counts.uncertain}</div>
                            <div className="label">Unclear</div>
                        </button>
                        <button className={`cit-cell cit-cell-btn cit-notfound ${filter === 'not_found' ? 'cit-active' : ''}`} onClick={() => setFilter('not_found')}>
                            <div className="cit-num mono">{counts.not_found}</div>
                            <div className="label">Not Found</div>
                        </button>
                    </div>
                </div>

                <div className="synth-detail-list">
                    {filtered.length === 0 && (
                        <div className="detail-empty mono">No citations in this category.</div>
                    )}
                    {filtered.map(c => {
                        const isOpen = expanded.has(c.id);
                        const ov = overrides[String(c.id)];
                        const status = ov ? getOverrideStatusInfo(ov.verdict) : getStatusInfo(c);
                        return (
                            <div key={c.id} className={`detail-row ${status.cls}`}>
                                <button className="detail-header" onClick={(e) => toggle(c.id, e.currentTarget.parentElement)}>
                                    <span className={`detail-badge ${status.cls}`}>
                                        {ov ? '\u270E' : status.badge}
                                    </span>
                                    <span className="detail-title mono">
                                        [{c.id}] {c.reference.title || c.reference.authors || 'Unknown'}
                                    </span>
                                    <span className="detail-chevron">{isOpen ? '\u25B4' : '\u25BE'}</span>
                                </button>
                                {isOpen && (
                                    <div className="detail-body">

                                        {/* ── Verdict explanation — most important, shown first ── */}
                                        <div className={`verdict-explanation verdict-expl-${ov ? ov.verdict : (c.verification?.verdict || 'uncertain')}`}>
                                            <span className="verdict-expl-icon">{ov ? '✎' : getStatusInfo(c).badge}</span>
                                            <span className="verdict-expl-text">
                                                {ov
                                                    ? `You manually marked this as "${ov.verdict}".${ov.notes ? ` Note: ${ov.notes}` : ''}`
                                                    : getVerdictExplanation(c)
                                                }
                                            </span>
                                        </div>

                                        {/* ── Evidence quote ── */}
                                        {c.verification?.evidence && (
                                            <div className="detail-evidence-block">
                                                <span className="label">What the source paper actually says</span>
                                                <blockquote className="detail-evidence-quote">
                                                    "{c.verification.evidence}"
                                                </blockquote>
                                            </div>
                                        )}

                                        {/* ── What was claimed ── */}
                                        <div className="detail-field">
                                            <span className="label">What this paper claims</span>
                                            <span className="detail-claim">{c.claim}</span>
                                        </div>

                                        {/* ── Source paper ── */}
                                        {c.source_found && (
                                            <div className="detail-field">
                                                <span className="label">Source paper located</span>
                                                <span className="detail-source-title">{c.source_found.title}</span>
                                                {c.source_found.authors && c.source_found.authors.length > 0 && (
                                                    <span className="detail-source-meta">
                                                        {c.source_found.authors.slice(0, 3).join(', ')}
                                                        {c.source_found.authors.length > 3 ? ' et al.' : ''}
                                                        {c.source_found.year ? ` · ${c.source_found.year}` : ''}
                                                        {c.source_found._source ? ` · via ${humanSourceName(c.source_found._source)}` : ''}
                                                    </span>
                                                )}
                                                <a
                                                    href={`https://scholar.google.com/scholar?q=${encodeURIComponent(c.source_found.title || c.reference.title || '')}`}
                                                    target="_blank" rel="noreferrer"
                                                    className="detail-scholar-link"
                                                >
                                                    Open in Google Scholar ↗
                                                </a>
                                            </div>
                                        )}

                                        {/* ── Reference metadata ── */}
                                        <div className="detail-field detail-field-meta">
                                            <span className="label">Cited as</span>
                                            <span>
                                                {c.reference.authors || 'Unknown authors'}
                                                {c.reference.year ? `, ${c.reference.year}` : ''}
                                            </span>
                                        </div>

                                        {/* ── How it was checked ── */}
                                        {c.verification && (
                                            <div className="detail-field detail-field-meta">
                                                <span className="label">How we checked this</span>
                                                <span>{humanMethodName(c.verification.method, c.verification.confidence)}</span>
                                            </div>
                                        )}

                                        {/* Manual override controls */}
                                        {ov && (
                                            <div className="override-banner">
                                                <span className="label">Your verdict: <strong>{ov.verdict}</strong></span>
                                                {ov.notes && <span className="override-notes">{ov.notes}</span>}
                                            </div>
                                        )}

                                        {editingId === c.id ? (
                                            <OverrideEditor
                                                current={ov}
                                                onSave={(v, n) => saveOverride(c.id, v, n)}
                                                onRemove={ov ? () => removeOverride(c.id) : undefined}
                                                onCancel={() => setEditingId(null)}
                                            />
                                        ) : (
                                            <button className="override-btn" onClick={() => setEditingId(c.id)}>
                                                {ov ? 'Edit Override' : 'Set Manual Verdict'}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                <div className="synth-conclusion rule-top">
                    <div className="label" style={{ marginBottom: '0.5rem' }}>Summary</div>
                    <p className="conclusion-text">{data.conclusion}</p>
                </div>
            </div>
        </div>
    );
}


function OverrideEditor({ current, onSave, onRemove, onCancel }: {
    current?: Override;
    onSave: (verdict: string, notes: string) => void;
    onRemove?: () => void;
    onCancel: () => void;
}) {
    const [verdict, setVerdict] = useState(current?.verdict || 'supported');
    const [notes, setNotes] = useState(current?.notes || '');

    return (
        <div className="override-editor">
            <div className="override-row">
                {VERDICT_OPTIONS.map(opt => (
                    <button
                        key={opt.value}
                        className={`ov-choice ${opt.cls} ${verdict === opt.value ? 'ov-selected' : ''}`}
                        onClick={() => setVerdict(opt.value)}
                    >
                        {opt.label}
                    </button>
                ))}
            </div>
            <textarea
                className="override-notes-input mono"
                placeholder="Notes (optional)..."
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
            />
            <div className="override-actions">
                <button className="ov-save" onClick={() => onSave(verdict, notes)}>Save</button>
                {onRemove && <button className="ov-remove" onClick={onRemove}>Remove</button>}
                <button className="ov-cancel" onClick={onCancel}>Cancel</button>
            </div>
        </div>
    );
}


function getStatusInfo(c: CitationDetail) {
    if (c.existence_status === 'not_found') {
        return {
            badge: '?',
            cls: 'status-notfound',
            reason: 'Not found in academic databases. May still be legitimate.',
        };
    }
    const verdict = c.verification?.verdict;
    if (verdict === 'supported') {
        return { badge: '\u2713', cls: 'status-ok', reason: 'Claim aligns with source material.' };
    }
    if (verdict === 'contradicted') {
        return { badge: '!', cls: 'status-conflict', reason: 'Claim may conflict with source. Review recommended.' };
    }
    return { badge: '~', cls: 'status-uncertain', reason: 'Could not confidently verify. Review recommended.' };
}

function getOverrideStatusInfo(verdict: string) {
    if (verdict === 'supported') return { badge: '\u2713', cls: 'status-ok', reason: '' };
    if (verdict === 'contradicted') return { badge: '!', cls: 'status-conflict', reason: '' };
    if (verdict === 'not_found') return { badge: '?', cls: 'status-notfound', reason: '' };
    return { badge: '~', cls: 'status-uncertain', reason: '' };
}

function getVerdictExplanation(c: CitationDetail): string {
    if (c.existence_status === 'not_found') {
        return "We searched three academic databases (Semantic Scholar, CrossRef, and OpenAlex) but could not locate this paper. It may be unpublished, paywalled, or the citation details may be inaccurate.";
    }

    const method = c.verification?.method || '';
    const verdict = c.verification?.verdict;
    const explanation = c.verification?.explanation?.trim();

    // Use Gemini's explanation when available and meaningful
    if (explanation && method === 'llm' && explanation.length > 20 && !explanation.startsWith('Parse error') && !explanation.startsWith('No claim')) {
        return explanation;
    }

    // Embedding-resolved (no LLM call needed)
    if (method === 'embedding' && verdict === 'supported') {
        return "The wording and meaning of this claim closely matches what the source paper actually says. Verified automatically using semantic similarity analysis.";
    }

    // LLM fallback cases — something went wrong during verification
    if (method === 'llm_fallback') {
        if (explanation?.includes('no readable text')) {
            return "The source paper was found in our database but no readable text could be retrieved — the paper may be behind a paywall. We could not verify the specific claim.";
        }
        if (explanation?.includes('No claim text')) {
            return "No specific claim text was extracted for this citation, so we could not verify what was being asserted.";
        }
        return "The source paper was found but we were unable to complete verification, possibly because the paper text was unavailable.";
    }

    // LLM verdicts without a usable explanation
    if (verdict === 'supported') {
        return "Our AI read the source paper and confirmed that the claim made in this citation is consistent with what the paper reports.";
    }
    if (verdict === 'contradicted') {
        return "Our AI found a mismatch between what this citation claims and what the source paper actually states. The source paper may say something different or opposite.";
    }
    if (verdict === 'uncertain') {
        if (method === 'embedding_low_similarity') {
            return "The language of this claim is very different from the source paper's text. This could mean the claim is inaccurate, or the paper is being cited for something it does not directly address.";
        }
        return "The source paper was found, but there is not enough clear evidence in its text to confirm or deny the specific claim being made. Manual review is recommended.";
    }

    return "This citation could not be fully verified. We recommend reviewing it manually.";
}

function humanSourceName(source: string): string {
    const map: Record<string, string> = {
        semantic_scholar: 'Semantic Scholar',
        crossref: 'CrossRef',
        openalex: 'OpenAlex',
        dblp: 'DBLP',
    };
    return map[source] || source;
}

function humanMethodName(method: string, confidence: number): string {
    const pct = Math.round(confidence * 100);
    switch (method) {
        case 'embedding':
            return `Checked using semantic text similarity — ${pct}% confidence`;
        case 'llm':
            return `Verified by AI reading the source paper — ${pct}% confidence`;
        case 'llm_fallback':
            return 'Could not fully verify — source text was unavailable';
        case 'embedding_low_similarity':
            return `Low semantic overlap detected, then reviewed by AI — ${pct}% confidence`;
        case 'embedding_uncertain':
            return `Inconclusive text similarity, then reviewed by AI — ${pct}% confidence`;
        case 'no_embedding_model':
            return `Reviewed by AI (embedding model unavailable) — ${pct}% confidence`;
        default:
            return method ? `Method: ${method}` : 'Verification method unknown';
    }
}
