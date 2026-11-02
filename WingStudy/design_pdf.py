"""Thrust-torque results by lambda, with embedded Times New Roman typography."""
from pathlib import Path
import math
import os
import tempfile
from xml.sax.saxutils import escape
import lambda_review as review


def frontier(rows):
    best=-math.inf;out=[]
    for r in sorted(rows,key=lambda r:(r[review.TORQUE],-r[review.THRUST],r['study'],r['id'])):
        if r[review.THRUST]>best:out.append(r);best=r[review.THRUST]
    return out


def font_paths():
    directory=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    paths={k:directory/file for k,file in [('regular','times.ttf'),('bold','timesbd.ttf'),('italic','timesi.ttf'),('boldItalic','timesbi.ttf')]}
    if not all(p.is_file() for p in paths.values()):raise ValueError('Times New Roman fonts are required for this report. Install the Times New Roman family on this computer.')
    return paths


def band_series(rows,studies,lo,hi,width):
    return [r for study in studies for r in review.band_winners([r for r in rows if r['study']==study['id']],lo,hi,width)]


def figures(model,rows,studies,series,envelope_rows,dest,lo,hi,fonts):
    import numpy as np
    from matplotlib import font_manager
    from matplotlib.offsetbox import DrawingArea,AnnotationBbox
    from matplotlib.patches import Polygon,Rectangle
    from matplotlib.lines import Line2D
    for file in fonts.values():font_manager.fontManager.addfont(str(file))
    colors={s['id']:s['color'] for s in studies};plt=model.ieee_style()
    with plt.rc_context({'font.family':'Times New Roman','font.size':10,'axes.spines.top':False,'axes.spines.right':False}):
        fig,ax=plt.subplots(figsize=(7.16,4.4),layout='constrained')
        unique={r['simulation_id'] or (r['study'],r['id']):r for r in rows}.values()
        ax.scatter([r[review.TORQUE] for r in unique],[r[review.THRUST] for r in unique],s=4,c='#c5c5c5',alpha=.4,linewidths=0)
        ymax=max(r[review.THRUST] for r in rows)*1.09;sampled=[]
        for study in studies:
            kept=[]
            for r in sorted((r for r in series if r['study']==study['id']),key=lambda r:-r[review.THRUST]):
                if all(math.hypot((r[review.TORQUE]-q[review.TORQUE])/(hi-lo),(r[review.THRUST]-q[review.THRUST])/ymax)>.075 for q in kept):kept.append(r)
            sampled.extend(kept)
        shared={}
        for r in sampled:
            key=r['simulation_id'] or (r['study'],r['id'])
            if key not in shared:shared[key]={**r,'sources':[r['study']]}
            else:shared[key]['sources'].append(r['study']);shared[key]['is_final']|=r['is_final']
        shown=sorted(shared.values(),key=lambda r:r['is_final'])
        span=max(max(p[0] for p in r['outline_m'])-min(p[0] for p in r['outline_m']) for r in rows);scale=26/max(span,1e-9)
        for r in shown:
            poly=np.array(r['outline_m']);lower=poly.min(axis=0);size=(poly.max(axis=0)-lower)*scale;v=(poly-lower)*scale;v[:,1]=size[1]-v[:,1]
            box=DrawingArea(max(size[0],1),max(size[1],1));patch=Polygon(v,facecolor=colors[r['study']],edgecolor='none');box.add_artist(patch)
            if len(r['sources'])>1:
                for j in range(int(size[0]/2)+1):
                    stripe=Rectangle((j*2,0),2,max(size[1],1),facecolor=colors[r['sources'][j%len(r['sources'])]],lw=0);stripe.set_clip_path(patch);box.add_artist(stripe)
            box.add_artist(Polygon(v,fill=False,edgecolor='black' if r['is_final'] else '#b0b0b0',lw=.7 if r['is_final'] else .4))
            ax.add_artist(AnnotationBbox(box,(r[review.TORQUE],r[review.THRUST]),frameon=False,pad=0,zorder=3 if r['is_final'] else 2))
        ax.set(xlim=(lo,hi),ylim=(0,ymax),xlabel='Peak wing-root torque (N m)',ylabel='Mean single-wing thrust (N)');ax.grid(alpha=.17);ax.set_axisbelow(True)
        bar=DrawingArea(scale*.1,8);bar.add_artist(Line2D([0,scale*.1],[4,4],color='black',lw=1.2));ax.add_artist(AnnotationBbox(bar,(.06,.91),xycoords='axes fraction',frameon=False));ax.text(.06,.82,'0.10 m',transform=ax.transAxes,fontsize=9)
        ax.legend(handles=[Line2D([],[],marker='s',linestyle='',color=s['color'],label=f"λ = {s['lambda_value']:g}") for s in studies],loc='lower right',frameon=False,fontsize=10)
        fig.savefig(dest/'torque_band_shapes.png',dpi=450);plt.close(fig)
        fig,ax=plt.subplots(figsize=(7.16,2.15),layout='constrained')
        for study,style in zip(studies,('-','--','-.')):
            path=frontier([r for r in envelope_rows if r['study']==study['id'] and r[review.TORQUE]<=hi])
            if not path:continue
            ax.step([*[r[review.TORQUE] for r in path],hi],[*[r[review.THRUST] for r in path],path[-1][review.THRUST]],where='post',color=study['color'],ls=style,lw=1.25,label=f"λ = {study['lambda_value']:g}")
        ax.set(xlim=(lo,hi),ylim=(0,ymax),xlabel='Available peak root torque (N m)',ylabel='Best mean thrust (N)');ax.grid(alpha=.17);ax.legend(loc='lower right',frameon=False,ncol=len(studies),fontsize=9)
        fig.savefig(dest/'thrust_torque_envelopes.png',dpi=450);plt.close(fig)


def export(model,data):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image,Flowable
    except ImportError as exc:raise ValueError('PDF export requires the report dependency. Run Setup Windows.cmd once.') from exc
    fonts=font_paths()
    for kind,name in [('regular','ReportTimes'),('bold','ReportTimesBold'),('italic','ReportTimesItalic'),('boldItalic','ReportTimesBoldItalic')]:
        if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(fonts[kind])))
    pdfmetrics.registerFontFamily('ReportTimes',normal='ReportTimes',bold='ReportTimesBold',italic='ReportTimesItalic',boldItalic='ReportTimesBoldItalic')
    result=review.export(model,data);b=review.bundle(model);rows,winners,lo,hi,width=review.selection(b,data)
    selected=data.get('studies',[s['id'] for s in b['studies']]);studies=[s for s in b['studies'] if s['id'] in selected]
    series=band_series(rows,studies,lo,hi,width)
    scope=data.get('scope','all')
    envelope_rows=[r for r in b['rows'] if r['study'] in selected and
        (scope=='all' or scope=='accepted' and r['is_accepted'] or scope=='final' and r['is_final'])]
    dest=(model.OUTPUTS/result['files'][0]).parent;figures(model,rows,studies,series,envelope_rows,dest,lo,hi,fonts)
    width_page=A4[0]-84;ref=b['references'];c=b['conditions'];a=studies[0]['search']
    styles={k:ParagraphStyle(k,fontName=font,fontSize=size,leading=leading,spaceAfter=after,textColor=colors.black) for k,font,size,leading,after in [
        ('title','ReportTimesBold',22,26,10),('heading','ReportTimesBold',12,15,7),
        ('body','ReportTimes',10.5,13,8),('caption','ReportTimes',8.5,10.5,7),('cell','ReportTimes',9,11,0)]}
    def clean(value):return str(value).replace('−','-').replace('–','-').replace('—','-').replace('\u2011','-')
    def p(text,style='body'):return Paragraph(clean(text),styles[style])
    def lit(text,style='body'):return p(escape(clean(text)),style)
    def num(x):return f'{x:.6g}'
    def image(file,width=width_page,height=300):
        from PIL import Image as PI
        with PI.open(dest/file) as im:w,h=im.size
        s=min(width/w,height/h);return Image(str(dest/file),width=w*s,height=h*s,hAlign='CENTER')
    def table(headers,values,colwidths):
        cells=[[p('<b>'+escape(str(v)).replace('\n','<br/>')+'</b>','cell') for v in headers]]+[[lit(v,'cell') for v in row] for row in values]
        t=Table(cells,colWidths=colwidths,repeatRows=1,hAlign='LEFT');t.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LINEABOVE',(0,0),(-1,0),.8,colors.black),('LINEBELOW',(0,0),(-1,0),.5,colors.black),
            ('LINEBELOW',(0,-1),(-1,-1),.6,colors.black),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]));return t

    class Equation(Flowable):
        """Vector fractions in real Times New Roman, with measured subscripts."""
        def __init__(self):super().__init__();self.width=width_page;self.height=63
        def draw(self):
            cv=self.canv;size=15;subsize=9
            def measure(base,sub=''):return pdfmetrics.stringWidth(base,'ReportTimesItalic',size)+pdfmetrics.stringWidth(sub,'ReportTimes',subsize)
            def term(x,y,base,sub=''):
                cv.setFont('ReportTimesItalic',size);cv.drawString(x,y,base);w=pdfmetrics.stringWidth(base,'ReportTimesItalic',size)
                cv.setFont('ReportTimes',subsize);cv.drawString(x+w,y-4,sub);return measure(base,sub)
            def fraction(x,base):
                w1=measure(base,'new');w2=measure(base,'current');minus=pdfmetrics.stringWidth(' - ','ReportTimes',size);w=max(w1+minus+w2,measure(base,'ref'))+12
                pos=x+6;pos+=term(pos,36,base,'new');cv.setFont('ReportTimes',size);cv.drawString(pos,36,' - ');pos+=minus;term(pos,36,base,'current')
                cv.setLineWidth(.65);cv.line(x,29,x+w,29);term(x+(w-measure(base,'ref'))/2,12,base,'ref');return w
            def fraction_width(base):return max(measure(base,'new')+pdfmetrics.stringWidth(' - ','ReportTimes',size)+measure(base,'current'),measure(base,'ref'))+12
            total=measure('ΔS')+5+17+fraction_width('T')+40+fraction_width('M')
            x=(width_page-total)/2;cv.setFont('ReportTimesItalic',size);cv.drawString(x,25,'ΔS');x+=measure('ΔS')+5
            cv.setFont('ReportTimes',size);cv.drawString(x,25,'=');x+=17;x+=fraction(x,'T')
            cv.setFont('ReportTimes',size);cv.drawString(x+7,25,'-');cv.setFont('ReportTimesItalic',size);cv.drawString(x+23,25,'λ');x+=40;fraction(x,'M')
            cv.setFont('ReportTimes',10);cv.drawRightString(width_page,25,'(1)')

    sources={s['id']:chr(65+i) for i,s in enumerate(studies)}
    distinct=len({r['simulation_id'] for r in rows})
    scope_label={'all':'all evaluated designs','accepted':'accepted evolution and seeds','final':'final accepted designs'}[scope]
    story=[p('Wing Shape Optimization Results','title'),
        lit(f"Mean single-wing thrust versus peak wing-root torque. Each search is shown separately: "+', '.join(f"λ = {s['lambda_value']:g}" for s in studies)+'.'),
        lit(f"Selection: {distinct} distinct simulations; {scope_label}; torque range {lo:g}-{hi:g} N m; band width {width:g} N m.",'caption'),
        lit('Highest-thrust shapes within each torque band','heading'),image('torque_band_shapes.png',height=320),
        lit('Each silhouette is the highest-thrust observed design in its torque interval for one lambda. Sampling is applied separately to each series for readability. Shapes share a physical scale and are centered on their simulated loads. Stripes indicate an identical simulation shared by studies. Black borders denote final accepted designs; grey borders denote earlier designs.','caption'),
        lit('Best observed thrust at or below each torque','heading'),image('thrust_torque_envelopes.png',height=155),
        lit('Step curves give max(T) among eligible designs with peak torque M no greater than the available torque. Lower-torque designs remain eligible even below the displayed minimum. These envelopes differ from within-band selection above; neither plot interpolates new simulations.','caption'),PageBreak(),
        lit('Representative torque-band results','heading')]
    ids=sorted({round(i*(len(winners)-1)/min(3,len(winners)-1)) for i in range(min(4,len(winners)))}) if len(winners)>1 else [0]
    values=[]
    for index in ids:
        band=winners[index]
        for study in studies:
            r=next((r for r in series if r['study']==study['id'] and abs(r['torque_band_min_nm']-band['torque_band_min_nm'])<1e-10),None)
            interval=f"{band['torque_band_min_nm']:.6g}-{band['torque_band_max_nm']:.6g}"
            values.append([interval,f"{study['lambda_value']:g}",num(r[review.THRUST]) if r else '-',num(r[review.TORQUE]) if r else '-',f"{1000*r['single_wing_span_m']:.2f}" if r else '-',str(r.get('global_case_no') or '-') if r else '-',sources[r['study']]+'/'+r['id'] if r else 'No eligible case'])
    story.append(table(['Torque band\n(N m)','λ','Mean thrust\n(N)','Peak torque\n(N m)','Span\n(mm)','Master #','Source / case'],values,[74,31,65,67,57,57,width_page-351]))
    story.append(Spacer(1,6))
    story.append(lit('Intervals start at the selected minimum. Internal upper edges belong to the next band; the final upper edge is included. A dash means that search has no eligible design in the interval. Full per-lambda band results remain in the CSV export.','caption'))
    tolerance='10<super>-6</super>' if a['score_tolerance']==1e-6 else f"{a['score_tolerance']:g}"
    story += [lit('Optimization method','heading'),Equation(),
        p(f"Accept a change only when ΔS &gt; {tolerance}. <i>T</i> denotes final-cycle mean single-wing thrust and <i>M</i> peak absolute root roll moment; current denotes the last accepted wing. Fixed normalization references are {ref['thrust_scale_N']:.6g} N for thrust and {ref['torque_scale_Nm']:.6g} N m for torque. λ weights torque reduction relative to thrust gain; selected searches use "+', '.join(f"{s['lambda_value']:g}" for s in studies)+'.'),
        lit(f"Five starting shape families at total spans 0.4, 0.6 and 0.8 m evolve independently, with eight chord-width variables. Root-to-tip coordinate trials start at ±{a['initial_step_m']:g} m, remember an improving direction, and receive one half-step refinement when that direction stalls. Root width is capped at 0.2 m. Outboard zero chords remove a contiguous suffix and shorten the wing. There is no search-time torque ceiling."),
        lit(f"Rigid Ptera UVLM; {c['frequency_hz']:g} Hz; {studies[0]['motion']['minimum_deg']:g}° to {studies[0]['motion']['maximum_deg']:g}° flap; {c['speed_mps']:g} m/s inflow; water ρ = {c['rho']:g} kg/m³, ν = {c['nu']:g} m²/s. Δt = {c['dt_s']:g} s, {c['cycles']} cycles, {c['span_panels']} × {c['chord_panels']} panels, {c['wake_model']} wake retaining {c['wake_cycles']:g} cycles.",'caption'),
        lit('Scope: best observed designs in this numerical search, not a proven global optimum. Loads exclude wing inertia and drivetrain conversion. Final selection requires mesh/time-step/wake checks and physical validation.','caption')]
    for s in studies:story.append(lit(f"{sources[s['id']]}: {s['id']} (λ = {s['lambda_value']:g})",'caption'))
    output=dest/'wing_design_report.pdf'
    with tempfile.TemporaryDirectory(prefix='wing-design-report-') as temp:
        path=Path(temp)/output.name
        doc=SimpleDocTemplate(str(path),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=34,bottomMargin=34,
            title='Wing Shape Optimization Results',author='Wing Studies',pageCompression=1)
        def footer(cv,document):
            cv.saveState();cv.setFont('ReportTimes',8);cv.setStrokeColor(colors.HexColor('#999999'));cv.setLineWidth(.3);cv.line(42,26,A4[0]-42,26)
            cv.drawString(42,15,'Wing shape optimization | Simulation results');cv.drawRightString(A4[0]-42,15,str(document.page));cv.restoreState()
        doc.build(story,onFirstPage=footer,onLaterPages=footer);os.replace(path,output)
    return {'file':str(output.relative_to(model.OUTPUTS)).replace('\\','/'),
        'note':'Results report with all selected lambdas on the thrust-torque shape plot; no single overall wing is selected.'}
