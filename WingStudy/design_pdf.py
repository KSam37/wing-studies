"""Concise design-selection report, with embedded Times New Roman typography."""
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


def figures(model,rows,points,best,path,dest,lo,hi,fonts):
    import numpy as np
    from matplotlib import font_manager
    from matplotlib.offsetbox import DrawingArea,AnnotationBbox
    from matplotlib.patches import Polygon
    from matplotlib.lines import Line2D
    for file in fonts.values():font_manager.fontManager.addfont(str(file))
    plt=model.ieee_style()
    with plt.rc_context({'font.family':'Times New Roman','font.size':10,'axes.spines.top':False,'axes.spines.right':False}):
        fig,ax=plt.subplots(figsize=(4.5,2.5),layout='constrained')
        poly=np.array(best['outline_m'])*1000
        ax.fill(*poly.T,facecolor='#d6e1e5',edgecolor='black',lw=1)
        ax.set_aspect('equal');ax.invert_yaxis();ax.set(xlabel='Root-to-tip direction (mm)',ylabel='Chord direction (mm)')
        ax.grid(alpha=.15);fig.savefig(dest/'selected_wing.png',dpi=350);plt.close(fig)
        fig,ax=plt.subplots(figsize=(7.16,3.5),layout='constrained')
        unique={r['simulation_id'] or (r['study'],r['id']):r for r in rows}.values()
        ax.scatter([r[review.TORQUE] for r in unique],[r[review.THRUST] for r in unique],s=6,c='#c5c5c5',alpha=.6,linewidths=0)
        ymax=max(r[review.THRUST] for r in rows)*1.08;shown=[]
        for r in reversed(points):
            if all(math.hypot((r[review.TORQUE]-q[review.TORQUE])/(hi-lo),(r[review.THRUST]-q[review.THRUST])/ymax)>.07 for q in shown):shown.append(r)
        span=max(max(p[0] for p in r['outline_m'])-min(p[0] for p in r['outline_m']) for r in rows)
        scale=27/max(span,1e-9)
        for r in reversed(shown):
            poly=np.array(r['outline_m']);lower=poly.min(axis=0);size=(poly.max(axis=0)-lower)*scale;v=(poly-lower)*scale;v[:,1]=size[1]-v[:,1]
            box=DrawingArea(max(size[0],1),max(size[1],1));box.add_artist(Polygon(v,facecolor='#d6e1e5',edgecolor='black',lw=.6))
            ax.add_artist(AnnotationBbox(box,(r[review.TORQUE],r[review.THRUST]),frameon=False,pad=0,zorder=3))
        ax.set(xlim=(lo,hi),ylim=(0,ymax),xlabel='Peak wing-root torque (N m)',ylabel='Mean single-wing thrust (N)');ax.grid(alpha=.17);ax.set_axisbelow(True)
        bar=DrawingArea(scale*.1,8);bar.add_artist(Line2D([0,scale*.1],[4,4],color='black',lw=1.2));ax.add_artist(AnnotationBbox(bar,(.06,.91),xycoords='axes fraction',frameon=False));ax.text(.06,.82,'0.10 m',transform=ax.transAxes,fontsize=9)
        fig.savefig(dest/'design_frontier.png',dpi=450);plt.close(fig)
        if path:
            ids=sorted({0,(len(path)-1)//2,len(path)-1});chosen=[path[i] for i in ids]
            all_points=np.array([q for p in chosen for q in p['outline_m']])*1000;loxy=all_points.min(axis=0);hixy=all_points.max(axis=0);pad=max(hixy-loxy)*.06
            fig,axes=plt.subplots(1,len(chosen),figsize=(7.16,1.75),layout='constrained',squeeze=False)
            for ax,i,p in zip(axes[0],ids,chosen):
                poly=np.array(p['outline_m'])*1000;ax.fill(*poly.T,facecolor='#d6e1e5',edgecolor='black',lw=.8)
                ax.set_aspect('equal');ax.set(xlim=(loxy[0]-pad,hixy[0]+pad),ylim=(hixy[1]+pad,loxy[1]-pad))
                ax.set_title('Seed' if i==0 else 'Selected design' if i==len(path)-1 else f'Accepted step {i}',fontsize=10)
                ax.set_xlabel(f"{p['thrust']:.4g} N; {p['torque']:.4g} N m",fontsize=9);ax.set_xticks([]);ax.set_yticks([])
                for spine in ax.spines.values():spine.set_visible(False)
            fig.savefig(dest/'selected_evolution.png',dpi=350);plt.close(fig)


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
    points=frontier(rows);best=points[-1];paths=[p for p in b['lineages'] if p['study'] in selected]
    history=next((p['points'][:i+1] for p in paths if p['study']==best['study'] for i,point in enumerate(p['points']) if point['id']==best['id']),None)
    baseline=next((p['points'][0] for p in paths if p['family']=='square' and abs((p['starting_total_span_m']-b['conditions']['gap_m'])/2-best['single_wing_span_m'])<1e-8),None)
    dest=(model.OUTPUTS/result['files'][0]).parent;figures(model,rows,points,best,history,dest,lo,hi,fonts)
    width_page=A4[0]-84;ref=b['references'];c=b['conditions'];a=studies[0]['search']
    styles={k:ParagraphStyle(k,fontName=font,fontSize=size,leading=leading,spaceAfter=after,textColor=colors.black) for k,font,size,leading,after in [
        ('title','ReportTimesBold',22,26,10),('heading','ReportTimesBold',12,15,7),
        ('body','ReportTimes',10.5,13,8),('caption','ReportTimes',8.5,10.5,7),('cell','ReportTimes',9,11,0)]}
    def clean(value):return str(value).replace('−','-').replace('–','-').replace('—','-').replace('\u2011','-')
    def p(text,style='body'):return Paragraph(clean(text),styles[style])
    def lit(text,style='body'):return p(escape(clean(text)),style)
    def num(x):return f'{x:.5g}'
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
    root=best['chords_m'][0];distinct=len({r['simulation_id'] for r in rows})
    story=[p('Optimal Wing Shape Selection','title'),
        p(f"The highest mean single-wing thrust in the selected dataset is <b>{num(best[review.THRUST])} N</b>, requiring <b>{num(best[review.TORQUE])} N m</b> peak root torque. The corresponding design is master case <b>#{best.get('global_case_no') or '-'} ({sources[best['study']]}/{escape(best['id'])})</b>.")]
    if baseline and baseline['thrust']>0 and baseline['torque']>0:
        dt=100*(best[review.THRUST]/baseline['thrust']-1);dm=100*(best[review.TORQUE]/baseline['torque']-1)
        story.append(lit(f"Relative to the rectangular seed at the same span, thrust is {abs(dt):.1f}% {'higher' if dt>=0 else 'lower'} and peak torque is {abs(dm):.1f}% {'higher' if dm>=0 else 'lower'} ({baseline['thrust']:.4g} N, {baseline['torque']:.4g} N m for the seed)."))
    metrics=table(['Selected geometry','Value'],[['Root-to-tip span',f"{1000*best['single_wing_span_m']:.2f} mm"],['Root chord',f'{root*1000:.2f} mm'],['Wing area',f"{best['area_m2']:.5g} m²"],['Chord nodes',str(len(best['sections']))]],[109,width_page-323-109])
    layout=Table([[image('selected_wing.png',315,185),metrics]],colWidths=[323,width_page-323]);layout.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]));story.append(layout)
    story.append(lit('Root-to-tip station / chord width (mm): '+ '; '.join(f"{s['y_m']*1000:.2f} / {s['chord_m']*1000:.2f}" for s in best['sections'])+'.','caption'))
    story += [lit('Thrust available across root-torque demand','heading'),image('design_frontier.png',height=265),
        lit('Grey points: evaluated designs. Wing silhouettes: sampled nondominated designs, each at its simulated thrust and torque and drawn to a common physical scale. A design is dominated if another supplies at least as much thrust with no greater torque.','caption'),
        lit(f"Selection: {distinct} distinct simulations; torque {lo:g}-{hi:g} N m; "+{'all':'all evaluated designs','accepted':'accepted evolution and seeds','final':'final accepted designs'}[data.get('scope','all')]+'. The maximum-thrust design is one endpoint of this tradeoff, not the preferred design for every actuator.','caption'),PageBreak()]
    story.append(lit('Design alternatives','heading'))
    ids=sorted({round(i*(len(points)-1)/min(5,len(points)-1)) for i in range(min(6,len(points)))}) if len(points)>1 else [0]
    short=[points[i] for i in ids]
    col=[69,65,65,65,61,width_page-325]
    story.append(table(['Peak torque\n(N m)','Mean thrust\n(N)','Span\n(mm)','Root chord\n(mm)','Master #','Source / case'],[
        [num(r[review.TORQUE]),num(r[review.THRUST]),f"{1000*r['single_wing_span_m']:.2f}",f"{1000*r['chords_m'][0]:.2f}",str(r.get('global_case_no') or '-'),sources[r['study']]+'/'+r['id']] for r in short],col))
    if history:
        stages='Seed, intermediate accepted state and selected design' if len(history)>2 else 'Seed and selected design' if len(history)==2 else 'Selected seed; no accepted shape changes were recorded'
        story += [Spacer(1,10),lit('Evolution of the selected design','heading'),image('selected_evolution.png',height=115),lit(stages+'. Shapes share a physical scale; labels give mean thrust and peak root torque.','caption')]
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
            title='Optimal Wing Shape Selection',author='Wing Studies',pageCompression=1)
        def footer(cv,document):
            cv.saveState();cv.setFont('ReportTimes',8);cv.setStrokeColor(colors.HexColor('#999999'));cv.setLineWidth(.3);cv.line(42,26,A4[0]-42,26)
            cv.drawString(42,15,'Wing design selection | Simulation results');cv.drawRightString(A4[0]-42,15,str(document.page));cv.restoreState()
        doc.build(story,onFirstPage=footer,onLaterPages=footer);os.replace(path,output)
    return {'file':str(output.relative_to(model.OUTPUTS)).replace('\\','/'),
        'note':'Concise wing-design report with embedded Times New Roman, design alternatives and the delta-score equation.'}
