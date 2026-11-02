"""Self-contained sharing report over saved lambda results; no simulations."""
from pathlib import Path
import os
import tempfile
from xml.sax.saxutils import escape
import lambda_review as review


def export(model,data):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image
    except ImportError as exc:raise ValueError('PDF export requires the report dependency. Run Setup Windows.cmd once.') from exc
    result=review.export(model,data);b=review.bundle(model)
    rows,winners,lo,hi,width=review.selection(b,data)
    selected=data.get('studies',[s['id'] for s in b['studies']])
    studies=[s for s in b['studies'] if s['id'] in selected]
    paths=[p for p in b['lineages'] if p['study'] in selected]
    dest=(model.OUTPUTS/result['files'][0]).parent
    import matplotlib
    fonts=Path(matplotlib.get_data_path())/'fonts/ttf'
    for name,file in [('ReportSans','DejaVuSans.ttf'),('ReportSansBold','DejaVuSans-Bold.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(fonts/file)))
    pdfmetrics.registerFontFamily('ReportSans',normal='ReportSans',bold='ReportSansBold',italic='ReportSans',boldItalic='ReportSansBold')
    ink=colors.HexColor('#19343f');muted=colors.HexColor('#62747d');line=colors.HexColor('#dbe4e6')
    styles={
        'title':ParagraphStyle('title',fontName='ReportSansBold',fontSize=23,leading=28,textColor=ink,spaceAfter=12),
        'heading':ParagraphStyle('heading',fontName='ReportSansBold',fontSize=14,leading=19,textColor=ink,spaceAfter=9),
        'body':ParagraphStyle('body',fontName='ReportSans',fontSize=9,leading=13,textColor=ink,spaceAfter=9),
        'small':ParagraphStyle('small',fontName='ReportSans',fontSize=7.5,leading=10.5,textColor=muted,spaceAfter=8),
        'table':ParagraphStyle('table',fontName='ReportSans',fontSize=7.2,leading=9.5,textColor=ink),
        'formula':ParagraphStyle('formula',fontName='ReportSansBold',fontSize=12,leading=19,textColor=ink,spaceAfter=12),
    }
    def clean(s):return str(s).replace('−','-').replace('–','-').replace('—','-').replace('\u2011','-')
    def p(text,style='body'):return Paragraph(clean(text),styles[style])
    def literal(text,style='body'):return p(escape(clean(text)),style)
    def num(value):return f'{value:.6g}' if isinstance(value,(float,int)) else str(value)
    scope=data.get('scope','all');scope_label={'all':'All evaluated designs','accepted':'Accepted evolution + seeds','final':'Final seed designs only'}[scope]
    content_width=A4[0]-80
    def table(header,values,widths=None,dense=False):
        cells=[[p(escape(str(v)),'table') for v in header]]
        cells.extend([[p(escape(clean(v)),'table') for v in row] for row in values])
        t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef4f7')),
            ('LINEBELOW',(0,0),(-1,0),.7,line),('LINEBELOW',(0,1),(-1,-1),.25,line),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),2 if dense else 5),('BOTTOMPADDING',(0,0),(-1,-1),2 if dense else 5)]))
        return t
    def image(filename,max_height=650):
        from PIL import Image as PILImage
        with PILImage.open(dest/filename) as im:w,h=im.size
        scale=min(content_width/w,max_height/h)
        return Image(str(dest/filename),width=w*scale,height=h*scale,hAlign='CENTER')
    story=[];ref=b['references'];c=b['conditions'];a=studies[0]['search']
    label=', '.join(f"λ = {s['lambda_value']:g}" for s in studies)
    story += [literal('WING STUDIES / SAVED SIMULATION RESULTS','small'),p('Wing shape search<br/>Lambda comparison','title'),literal(label,'heading')]
    story += [literal(f'Torque range {lo:g}-{hi:g} N m | Band width {width:g} N m | {scope_label}'),
        literal(f"{len(rows)} study/case occurrences in range; {len({r['simulation_id'] for r in rows})} distinct simulations; {len(winners)} occupied pooled torque bands."),
        literal('Acceptance equation','heading'),
        p('ΔS = (T<sub>new</sub> - T<sub>current</sub>)/T<sub>ref</sub><br/>'
          '       - λ (M<sub>new</sub> - M<sub>current</sub>)/M<sub>ref</sub>','formula'),
        literal(f"T is final-cycle mean single-wing thrust; M is peak absolute wing-root roll moment. Current is the last accepted wing. Tref = {ref['thrust_scale_N']:.8g} N and Mref = {ref['torque_scale_Nm']:.8g} N m remain fixed. Accept only when ΔS > {a['score_tolerance']:g}."),
        p('<b>Lambda is the dimensionless torque weight.</b> Larger λ penalizes a normalized torque increase more strongly. There is no torque ceiling during optimization. Torque bands select designs after the search; thrust/torque is not energy efficiency.')]
    overview=[]
    for s in studies:
        sr=[r for r in rows if r['study']==s['id']];best=max(sr,key=lambda r:r[review.THRUST]) if sr else None
        overview.append([num(s['lambda_value']),s['evaluated'],s['new_simulations'],s['cache_hits'],s['accepted_changes'],len(sr),num(best[review.THRUST]) if best else 'None'])
    story += [literal('Study overview','heading'),table(['λ','All cases','New solves','Cached','Accepted changes','In range','Best T in range (N)'],overview,[37,62,65,55,82,60,content_width-361]),Spacer(1,10),
        literal('All cases/new solves/cached/accepted changes describe each complete saved study. In-range counts and thrust follow the selected filters. Cached occurrences across studies are not independent replications.','small'),
        literal('Saved driving and numerical conditions','heading'),
        literal(f"{c['frequency_hz']:g} Hz; {studies[0]['motion']['minimum_deg']:g}° to {studies[0]['motion']['maximum_deg']:g}° nominal flap; {c['speed_mps']:g} m/s inflow. Water: ρ = {c['rho']:g} kg/m³, ν = {c['nu']:g} m²/s. Δt = {c['dt_s']:g} s; {c['cycles']} cycles; {c['span_panels']} span × {c['chord_panels']} chord panels; {c['wake_model']} wake with {c['wake_cycles']:g} retained cycles."),
        literal('Driving conditions and reference scales match across the curated studies.' if b['comparable'] else 'WARNING: saved conditions or reference scales differ; compare only matched configurations.','small'),PageBreak()]
    story += [literal('Observed thrust versus peak root torque','heading'),image('lambda_comparison.png',300),
        literal('Left: best observed thrust at or below each torque budget (step envelope). Right: the highest-thrust design within each band, selected separately for each lambda. Silhouettes share a physical scale; striped wings are identical simulations shared by studies. Black borders denote final accepted designs; grey borders denote earlier designs. Markers are sampled for readability; no new shapes or loads are interpolated.','small'),
        literal('Representative pooled band winners','heading')]
    # Spread the shortlist across torque, not just high-thrust/high-area designs.
    indices=sorted({round(i*(len(winners)-1)/min(5,len(winners)-1)) for i in range(min(6,len(winners)))}) if len(winners)>1 else [0]
    samples=[winners[i] for i in indices]
    def winner_row(r):return [f"{r['torque_band_min_nm']:.6g}-{r['torque_band_max_nm']:.6g}",num(r[review.THRUST]),num(r[review.TORQUE]),num(r['lambda_value']),str(r.get('global_case_no') or '-'),r['id'],num(r['single_wing_span_m'])]
    widths=[76,60,68,35,55,116,content_width-410]
    story += [table(['Band (N m)','Thrust (N)','Peak M (N m)','λ','Master #','Local case','Span (m)'],[winner_row(r) for r in samples],widths),Spacer(1,12),
        literal('How to select a wing','heading'),
        literal('Use the torque band relevant to your hardware, inspect its highest-thrust candidate, then compare nearby bands and geometry. Bands are intervals, not hardware ceilings; a band winner can still be dominated by a design in another interval. The appendix lists every pooled band winner. Equal thrust is resolved by lower torque.'),
        literal('No unique universal winner is implied. The observed frontier and the similarity of final shapes do not prove a global optimum.','small'),PageBreak()]
    story += [literal('Independent seed evolutions, grouped by lambda','heading'),image('seed_evolutions.png',655),
        literal('Complete accepted histories for studies represented in the torque selection. Family colors identify seed shapes; line styles identify starting spans. Dashed paths follow chronological accepted changes; faint wings are seeds and black-edged wings are final states. Shared axes and physical silhouette scale support comparison. These full histories are not truncated by the torque-band filter.','small'),PageBreak()]
    story += [literal('Progress audit and methodology','heading'),image('evolution_audit.png',255),
        literal('Each line shows gain from its own seed under its study’s fixed-lambda score. Score gains are not a common efficiency measure across lambdas. A monotonic accepted score need not mean monotonic thrust or prove convergence.','small'),
        literal('Search procedure','heading'),
        literal(f"Five seed families at three starting total spans (0.4, 0.6, 0.8 m, including {c['gap_m']:g} m hinge gap) evolve independently, with eight chord nodes each. Initial ±{a['initial_step_m']:g} m width probes choose an improving direction. Root-to-tip passes then reuse that sign. A failed/blocked full step gets one half-step trial; that chord is then retired, except a newly exposed tip can be revisited."),
        literal('Root width may shrink below its 0.2 m cap. Chords decrease or stay equal outboard; the first two have a 0.01 m floor. Outer nodes may become zero as a contiguous suffix, shortening the actual span. This is a bounded coordinate finite-difference search, not a derivative-stationarity certificate.'),
        literal('Eligibility and limitations','heading'),literal(b['limitations']),
        literal('Only successful isolated-wing cases with positive mean thrust and the saved cycle-repeatability flag enter comparisons. This settling flag is not a discretization-error bound. Reused simulations are counted once by identity for pooled selection, while independent seed histories remain separate.'),
        literal('Source studies (stable identifiers)','heading')]
    for s in studies:story.append(literal(f"λ = {s['lambda_value']:g}: {s['id']}",'small'))
    story += [PageBreak(),literal('Appendix: all pooled torque-band winners','heading'),
        literal(f'{len(winners)} occupied bands, ordered by torque. Empty bands are not interpolated. Internal upper edges belong to the next band; the final upper edge is included. Span is the actual root-to-tip length of one wing. Match λ and local case to the source-study identifiers on the previous page.','small'),
        table(['Band (N m)','Thrust (N)','Peak M (N m)','λ','Master #','Local case','Span (m)'],[winner_row(r) for r in winners],widths,dense=True)]
    output=dest/'lambda_report.pdf'
    with tempfile.TemporaryDirectory(prefix='wing-report-') as temporary:
        path=Path(temporary)/'lambda_report.pdf'
        doc=SimpleDocTemplate(str(path),pagesize=A4,leftMargin=40,rightMargin=40,topMargin=38,bottomMargin=38,
            title='Wing shape search - lambda comparison',author='Wing Studies',pageCompression=1)
        def footer(canvas,document):
            canvas.saveState();canvas.setStrokeColor(line);canvas.line(40,29,A4[0]-40,29)
            canvas.setFont('ReportSans',7);canvas.setFillColor(muted);canvas.drawString(40,18,'Wing Studies | Saved rigid UVLM results | Screening, not hardware validation')
            canvas.drawRightString(A4[0]-40,18,str(document.page));canvas.restoreState()
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
        os.replace(path,output)
    return {'file':str(output.relative_to(model.OUTPUTS)).replace('\\','/'),
        'note':'Self-contained PDF with selected comparisons, full seed evolutions, methods and all pooled band winners.'}
