"""Gere referências sintéticas independentes, reconstruções e uma galeria comparativa."""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'interface-xray/scripts'))
import contour_tools as ct
import contour_geometry as geo


def draw(size, items, background=(25,30,40)):
    scale=4
    image=Image.new('RGB',(size[0]*scale,size[1]*scale),background)
    pen=ImageDraw.Draw(image)
    for kind,shape,color in items:
        if kind=='poly':
            pen.polygon([(x*scale,y*scale) for x,y in shape],fill=color)
        else:
            x,y,r=shape
            pen.ellipse(((x-r)*scale,(y-r)*scale,(x+r)*scale,(y+r)*scale),fill=color)
    return np.asarray(image.resize(size,Image.Resampling.BOX),float)


def cases():
    blue=(40,120,220)
    chamfer=[(40,30),(160,30),(172,42),(172,100),(160,112),(40,112),(28,100),(28,42)]
    asymmetric=[(45,40),(150,28),(172,92),(112,132),(48,108)]
    yield 'chanfros',draw((200,140),[('poly',chamfer,blue)]),(28,30,145,83),{}, {'vertices':chamfer}
    yield 'assimetrico',draw((200,150),[('poly',asymmetric,(200,90,60))]),(45,28,127,104),{}, {'vertices':asymmetric}
    t=np.linspace(0,1,200)[:,None]
    def cubic(control):
        a,b,c,d=np.asarray(control,float)
        return (1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d
    top=cubic([(30,80),(60,10),(140,10),(170,80)])
    bottom=cubic([(170,80),(140,150),(60,150),(30,80)])
    curve=np.vstack([top,bottom[1:]])
    yield 'bezier',draw((200,160),[('poly',curve,(120,60,200))]),(28,8,145,145),{}, {'curve':curve.tolist()}
    yield 'anel',draw((200,180),[('circle',(100,90,60),(230,230,230)),('circle',(100,90,52),blue)]),(40,30,120,120),{}, {'radius':52,'offsets':[8]}
    yield 'borda-dupla',draw((200,180),[('circle',(100,90,62),(230,230,230)),('circle',(100,90,58),(20,20,20)),('circle',(100,90,50),blue)]),(38,28,124,124),{}, {'radius':50,'offsets':[8,12]}
    y,x=np.mgrid[:160,:220]; x=x+0.5; y=y+0.5
    distance=np.hypot(np.maximum(np.maximum(70-x,0),x-150),np.maximum(np.maximum(50-y,0),y-110))
    alpha=0.6*np.exp(-distance**2/(2*5.**2))
    image=np.array([20,25,35])*(1-alpha[...,None])+np.array([255,200,80])*alpha[...,None]
    image[(x>=70)&(x<150)&(y>=50)&(y<110)]=blue
    yield 'brilho',image,(70,50,80,60),{'margin':30},{'sigma':5.}
    panel=[(50,40),(170,40),(170,120),(50,120)]
    occluder=[(140,25),(200,25),(200,135),(140,135)]
    yield 'oclusao',draw((220,150),[('poly',panel,blue),('poly',occluder,(250,250,250))]),(50,40,120,80),{'exclusions':[{'x':140,'y':25,'width':60,'height':110}]},{'vertices':[(50,40),(50,120)],'only_visible_vertices':True}
    background=np.random.default_rng(1).uniform(0,255,(150,200,3))
    image=background.copy(); image[40:110,40:160]=0.8*np.array(blue)+0.2*background[40:110,40:160]
    yield 'fundo-complexo',image,(36,36,128,78),{}, {'bbox':[40,40,160,110]}


def generate(output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    summary=[]
    for name,array,bbox,kwargs,truth in cases():
        folder=output/name; folder.mkdir()
        source=folder/'reference.png'
        Image.fromarray(np.clip(np.rint(array),0,255).astype('uint8')).save(source)
        ct.analyze_element(source,bbox,folder/'analysis',**kwargs)
        model=json.loads((folder/'analysis/element.json').read_text(encoding='utf-8'))
        metrics=json.loads((folder/'analysis/metrics.json').read_text(encoding='utf-8'))
        origin=np.array([model['analysis_frame']['x'],model['analysis_frame']['y']])
        vertices=np.asarray(model['geometry']['vertices_crop']).reshape(-1,2)+origin
        errors={}
        if 'vertices' in truth:
            errors['vertex_max_px']=float(max(np.min(np.linalg.norm(vertices-np.asarray(p),axis=1)) for p in truth['vertices']))
        if 'sigma' in truth:
            glow=model['effects']['glow_or_shadow']
            errors['sigma_abs_px']=abs(glow['sigma_px']-truth['sigma']) if glow else None
        if 'offsets' in truth:
            measured=[c['offset_px']['median'] for c in model['contours'][1:]]
            errors['offset_abs_px']=[abs(a-b) for a,b in zip(measured,truth['offsets'])]
        summary.append({'case':name,'known_parameters':truth,'recovered_vertices_image':vertices.tolist(),
                        'parameter_errors':errors,'metrics':metrics,'model':str(folder/'analysis/element.json')})
        print(name,errors,flush=True)
    width,row_height=1000,205
    gallery=Image.new('RGB',(width,50+row_height*len(summary)),(18,21,28))
    pen=ImageDraw.Draw(gallery)
    try:
        font=ImageFont.truetype('arial.ttf',16)
    except OSError:
        font=ImageFont.load_default()
    for col,label in enumerate(('Original sintetico','Reconstrucao em contexto','Bordas detectadas','Diferenca x6 (exibicao)')):
        pen.text((col*250+8,8),label,fill='white',font=font)
    for row,entry in enumerate(summary):
        folder=output/entry['case']; analysis=folder/'analysis'
        images=[folder/'reference.png',analysis/'diagnostics/full-render.png',analysis/'diagnostics/edges_x4.png',analysis/'diagnostics/full-difference.png']
        for col,file in enumerate(images):
            with Image.open(file) as source:
                image=source.convert('RGB')
                if col==3:
                    image=image.point(lambda x:min(255,x*6))
                image=ImageOps.contain(image,(240,170),Image.Resampling.NEAREST)
                gallery.paste(image,(col*250+5,50+row*row_height+25))
        pen.text((8,50+row*row_height),entry['case'],fill='white',font=font)
    gallery.save(output/'comparison-gallery.png')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return output/'comparison-gallery.png'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,help='Pasta nova; resultados anteriores são preservados.')
    print(generate(parser.parse_args().output_dir))
