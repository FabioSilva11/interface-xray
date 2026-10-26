"""Diagnósticos espaciais e máscaras explícitas para a análise de contornos."""
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
import contour_geometry as geo


def encode_mask(mask):
    """RLE por linhas: [y,x_inicial,x_final_exclusivo]."""
    runs = []
    for y, row in enumerate(mask):
        changes = np.diff(np.r_[False, row, False].astype(int))
        runs.extend([[y, int(a), int(b)] for a,b in zip(np.where(changes==1)[0], np.where(changes==-1)[0])])
    return runs


def decode_mask(runs, shape):
    result = np.zeros(shape, dtype=bool)
    for y,a,b in runs:
        if not (type(y) is int and type(a) is int and type(b) is int and 0 <= y < shape[0] and 0 <= a < b <= shape[1]):
            raise ValueError('Máscara RLE inválida no estado da revisão.')
        result[y,a:b] = True
    return result


def _png(array, path):
    buffer = BytesIO()
    Image.fromarray(np.clip(np.rint(array),0,255).astype('uint8')).save(buffer,format='PNG')
    with path.open('xb') as stream:
        stream.write(buffer.getvalue())


def write_context(output, source, full_rgb, frame, rgba, unknown, polygon, holes=(), distance_field=None):
    """Composição contextual; pixels fora do componente são preservados, não reconstruídos."""
    output, source = Path(output), Path(source)
    x,y,w,h = frame
    folder = output/'diagnostics'
    signed = geo.signed_distance(polygon, (h,w)) if distance_field is None else distance_field
    for hole in holes:
        signed = np.maximum(signed,-geo.signed_distance(hole,(h,w)))
    alpha = rgba[...,3]/255
    crop = full_rgb[y:y+h,x:x+w]
    background_pixels = crop[(alpha<0.001) & (signed>4) & ~unknown]
    background = np.median(background_pixels,axis=0) if len(background_pixels) else np.array([255.,255.,255.])
    composite = rgba[...,:3]*alpha[...,None] + background*(1-alpha[...,None])
    support = (alpha>0.001) & ~unknown
    scene = full_rgb.copy()
    patch = scene[y:y+h,x:x+w]
    patch[support] = composite[support]
    original = output/('source-original'+source.suffix.lower())
    with original.open('xb') as stream:
        stream.write(source.read_bytes())
    _png(scene, folder/'full-render.png')
    _png((full_rgb+scene)/2,folder/'full-overlay.png')
    _png(np.abs(full_rgb-scene),folder/'full-difference.png')
    _png(unknown.astype(float)*255,folder/'unknown-mask.png')
    with (output/'sdf.npy').open('xb') as stream:
        np.save(stream,signed.astype('float32'),allow_pickle=False)
    metrics = {
        'scope':'componente em contexto; exterior e oclusões preservados da captura, não reconstruídos',
        'evaluated_pixels':int(support.sum()), 'unknown_pixels_excluded':int(unknown.sum()),
        'mae_rgb_on_support':float(np.abs(crop-composite)[support].mean()) if support.any() else None,
        'background_rgb_estimate':background.tolist(),
        'background_evidence':'estimado pela mediana externa; branco proposto se não houver amostras',
        'not_a_full_screen_fidelity_score':True,
    }
    return {'original':str(original),'full_render':str(folder/'full-render.png'),
            'full_overlay':str(folder/'full-overlay.png'),'full_difference':str(folder/'full-difference.png'),
            'unknown_mask':str(folder/'unknown-mask.png'),'sdf':str(output/'sdf.npy'),
            'sdf_convention':('negativo dentro; px_imagem; centros dos pixels; aproximação polilinear das curvas' if distance_field is None
                              else 'não assinado; caminho aberto; px_imagem; centros dos pixels'),
            'metrics':metrics}
