import { useEffect, useRef } from 'react';
import './StatCards.css';

const STATS = [
    {
        stat: '21%',
        watermark: '21',
        headline: 'of all ICLR 2026 peer reviews were fully AI-generated',
        sub: 'Out of 75,800 reviews submitted — identified by GPTZero analysis. Human reviewers are being replaced faster than the system can adapt.',
        source: 'GPTZero / HowAIWorks, 2026',
        tag: 'Peer Review',
        index: '01 / 06',
        accent: 'red',
    },
    {
        stat: '100+',
        watermark: '100',
        headline: 'hallucinated citations found in NeurIPS 2025 accepted papers',
        sub: 'Fabricated references embedded in 53 papers that beat 15,000+ competitors. These papers passed full peer review — every checkpoint failed.',
        source: 'ByteIota Research, NeurIPS 2025',
        tag: 'Citation Fraud',
        index: '02 / 06',
        accent: 'red',
    },
    {
        stat: '3×',
        watermark: '3×',
        headline: 'ICLR submission volume tripled in just two years',
        sub: 'From ~7,000 in 2024 to over 20,000 in 2026. Reviewers are overwhelmed. The volume alone makes fraud invisible.',
        source: 'Science Magazine, 2026',
        tag: 'Submission Flood',
        index: '03 / 06',
        accent: 'gold',
    },
    {
        stat: '53',
        watermark: '53',
        headline: 'accepted NeurIPS papers contained AI-fabricated references',
        sub: 'Papers that passed full peer review despite containing non-existent citations. The gatekeeping system failed at every single stage.',
        source: 'ByteIota / Science, 2025',
        tag: 'False Acceptance',
        index: '04 / 06',
        accent: 'red',
    },
    {
        stat: '★ 0',
        watermark: '0',
        headline: 'tools exist that researchers can use before submitting',
        sub: 'GPTZero builds detection for institutions. Nobody built the tool for the author. That\'s the gap Resify was built to close.',
        source: 'Market Gap Analysis',
        tag: 'The Gap',
        index: '05 / 06',
        accent: 'green',
    },
    {
        stat: null,
        watermark: '',
        headline: '— Hany Farid, UC Berkeley computer scientist and computational forensics expert',
        sub: 'The consensus among leading researchers is no longer cautious concern — it\'s alarm. The infrastructure of academic trust is under systematic attack.',
        source: 'Science Magazine, 2026',
        tag: 'Expert Verdict',
        index: '06 / 06',
        accent: 'ink',
        quote: '"The whole system is breaking down."',
    },
];

export function StatCards() {
    const stickiesRef = useRef<(HTMLDivElement | null)[]>([]);
    const dotsRef = useRef<(HTMLDivElement | null)[]>([]);

    useEffect(() => {
        const stickies = stickiesRef.current.filter(Boolean) as HTMLDivElement[];
        const dots = dotsRef.current.filter(Boolean) as HTMLDivElement[];

        // Scroll reveal + progress dots
        const obs = new IntersectionObserver(
            entries => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('sc-visible');
                        const idx = stickies.indexOf(entry.target as HTMLDivElement);
                        dots.forEach((d, i) => d.classList.toggle('sc-dot-on', i === idx));
                    }
                });
            },
            { threshold: 0.25, rootMargin: '-80px 0px -80px 0px' }
        );
        stickies.forEach(s => obs.observe(s));

        // 3D tilt + shimmer on mouse move
        const cards = stickies.map(s => s.querySelector<HTMLDivElement>('.sc-card')).filter(Boolean) as HTMLDivElement[];
        const onMove = (card: HTMLDivElement) => (e: MouseEvent) => {
            const r = card.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width - 0.5;
            const y = (e.clientY - r.top) / r.height - 0.5;
            card.style.transform = `perspective(900px) rotateY(${x * 10}deg) rotateX(${-y * 10}deg) translateZ(12px)`;
            card.style.setProperty('--mx', `${(x + 0.5) * 100}%`);
            card.style.setProperty('--my', `${(y + 0.5) * 100}%`);
        };
        const onLeave = (card: HTMLDivElement) => () => { card.style.transform = ''; };

        const handlers: Array<[HTMLDivElement, (e: MouseEvent) => void, () => void]> = [];
        cards.forEach(card => {
            const move = onMove(card);
            const leave = onLeave(card);
            card.addEventListener('mousemove', move);
            card.addEventListener('mouseleave', leave);
            handlers.push([card, move, leave]);
        });

        // Parallax watermarks on scroll
        const onScroll = () => {
            const sy = window.scrollY;
            document.querySelectorAll<HTMLDivElement>('.sc-watermark').forEach(wm => {
                wm.style.transform = `translateY(${sy * 0.04}px)`;
            });
        };
        window.addEventListener('scroll', onScroll, { passive: true });

        return () => {
            obs.disconnect();
            handlers.forEach(([card, move, leave]) => {
                card.removeEventListener('mousemove', move);
                card.removeEventListener('mouseleave', leave);
            });
            window.removeEventListener('scroll', onScroll);
        };
    }, []);

    return (
        <section className="sc-section">
            {/* Section header */}
            <div className="sc-header">
                <div className="sc-header-label label">The Evidence</div>
                <div className="sc-header-title">
                    Why peer review is in crisis — and why nothing is fixed yet
                </div>
            </div>

            {/* Cards track */}
            <div className="sc-track">
                {STATS.map((item, i) => (
                    <div key={i}>
                        <div
                            className={`sc-sticky sc-c${i}`}
                            ref={el => { stickiesRef.current[i] = el; }}
                        >
                            <div className={`sc-card sc-accent-${item.accent}`}>
                                {/* Left accent bar */}
                                <div className="sc-accent-bar" />
                                {/* Index badge */}
                                <div className="sc-index mono">{item.index}</div>
                                {/* Watermark */}
                                {item.watermark && (
                                    <div className="sc-watermark">{item.watermark}</div>
                                )}
                                {/* Shimmer overlay */}
                                <div className="sc-shimmer" />

                                <div className="sc-tag label">{item.tag}</div>

                                {item.quote ? (
                                    <div className="sc-quote">{item.quote}</div>
                                ) : (
                                    <div className="sc-stat">{item.stat}</div>
                                )}

                                <div className="sc-headline">{item.headline}</div>
                                <div className="sc-body">{item.sub}</div>

                                <div className="sc-footer">
                                    <span className="sc-source mono">{item.source}</span>
                                    <span className="sc-arrow">→</span>
                                </div>
                            </div>
                        </div>
                        <div className={`sc-spacer ${i === STATS.length - 1 ? 'sc-spacer-last' : ''}`} />
                    </div>
                ))}
            </div>

            {/* Progress dots */}
            <div className="sc-dots">
                {STATS.map((_, i) => (
                    <div
                        key={i}
                        className={`sc-dot ${i === 0 ? 'sc-dot-on' : ''}`}
                        ref={el => { dotsRef.current[i] = el; }}
                    />
                ))}
            </div>
        </section>
    );
}
