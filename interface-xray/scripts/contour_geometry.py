#!/usr/bin/env python3
"""Primitivas numéricas para reconstrução de contornos (requer NumPy opcional).

Convenções: imagens são arrays (altura, largura[, canais]); coordenadas são (x, y)
contínuas, e o pixel da linha r e coluna c ocupa [c, c+1) × [r, r+1), com centro
em (c+0.5, r+0.5). Funções puras: não gravam arquivos nem acessam a rede.
"""

from __future__ import annotations

from collections import deque
import heapq
import math

import numpy as np

try:
    from scipy.spatial import cKDTree as _KDTree
except ImportError:
    _KDTree = None  # Acelerador opcional; resultados continuam definidos pelo mesmo conjunto de pontos.


def nearest_distances(points, targets):
    points, targets = np.asarray(points), np.asarray(targets)
    if len(points) == 0 or len(targets) == 0:
        raise GeometryError('A comparação exige conjuntos não vazios de pontos.')
    if _KDTree is not None:
        return _KDTree(targets).query(points)[0]
    return np.concatenate([np.sqrt(np.min(np.sum((batch[:,None]-targets[None])**2,axis=2),axis=1))
                           for batch in np.array_split(points, max(1, int(np.ceil(len(points)/256))))])


def trace_edge_path(edges, start, end):
    """Menor caminho na componente conectada Canny; não atravessa lacunas desconhecidas."""
    pixels=np.column_stack(np.nonzero(edges))[:,::-1]
    if not len(pixels):
        raise GeometryError('Nenhuma borda na região.')
    anchors=[]
    for point in (start,end):
        distances=np.sum((pixels-np.asarray(point))**2,axis=1)
        index=int(np.argmin(distances))
        if distances[index]>16:
            raise GeometryError('Âncora distante das bordas detectadas; indique uma extremidade observada.')
        anchors.append(tuple(map(int,pixels[index])))
    a,b=anchors
    queue=[(0.,a)]
    distance={a:0.}
    previous={}
    while queue:
        cost,point=heapq.heappop(queue)
        if cost>distance[point]:
            continue
        if point==b:
            path=[b]
            while path[-1]!=a:
                path.append(previous[path[-1]])
            return np.array(path[::-1],float)+0.5
        for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            target=(point[0]+dx,point[1]+dy)
            if not (0<=target[0]<edges.shape[1] and 0<=target[1]<edges.shape[0] and edges[target[1],target[0]]):
                continue
            candidate=cost+math.hypot(dx,dy)
            if candidate<distance.get(target,float('inf')):
                distance[target]=candidate
                previous[target]=point
                heapq.heappush(queue,(candidate,target))
    raise GeometryError('Bordas desconectadas entre as âncoras; a ligação oculta não foi inventada.')


class GeometryError(ValueError):
    """Dados insuficientes ou inválidos para uma estimativa geométrica."""


# tan(22,5°): separa as direções do gradiente em quatro setores para a supressão não máxima.
_SECTOR = 0.41421356


# --------------------------------------------------------------------------- imagem

def luminance(rgb):
    """Luminância aproximada (Rec. 709, valores 0–255) de um array RGB."""
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _kernel(sigma):
    radius = max(1, int(math.ceil(3 * sigma)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    weights = np.exp(-offsets * offsets / (2 * sigma * sigma))
    return weights / weights.sum()


def _convolve_axis(array, weights, axis):
    pad = len(weights) // 2
    pads = [(0, 0)] * array.ndim
    pads[axis] = (pad, pad)
    padded = np.pad(array, pads, mode="edge")
    length = array.shape[axis]
    result = np.zeros(array.shape, dtype=np.float64)
    for index, weight in enumerate(weights):
        window = [slice(None)] * array.ndim
        window[axis] = slice(index, index + length)
        result += weight * padded[tuple(window)]
    return result


def gaussian_blur(array, sigma):
    """Desfoque gaussiano separável em um canal 2D."""
    weights = _kernel(sigma)
    return _convolve_axis(_convolve_axis(np.asarray(array, dtype=np.float64), weights, 0), weights, 1)


def box_filter(array, size):
    """Média uniforme separável, usada pelo SSIM local."""
    weights = np.full(size, 1.0 / size)
    return _convolve_axis(_convolve_axis(np.asarray(array, dtype=np.float64), weights, 0), weights, 1)


def sobel_gradients(channel):
    """Gradientes Sobel (gx, gy) de um canal 2D, normalizados por 8."""
    padded = np.pad(np.asarray(channel, dtype=np.float64), 1, mode="edge")
    top, middle, bottom = padded[:-2], padded[1:-1], padded[2:]
    gx = (top[:, 2:] + 2 * middle[:, 2:] + bottom[:, 2:]) - (top[:, :-2] + 2 * middle[:, :-2] + bottom[:, :-2])
    gy = (bottom[:, :-2] + 2 * bottom[:, 1:-1] + bottom[:, 2:]) - (top[:, :-2] + 2 * top[:, 1:-1] + top[:, 2:])
    return gx / 8.0, gy / 8.0


def _shift(array, dr, dc):
    """Retorna b com b[r, c] = a[r + dr, c + dc], preenchendo com zero fora da imagem."""
    result = np.zeros_like(array)
    height, width = array.shape
    result[max(0, -dr):height - max(0, dr), max(0, -dc):width - max(0, dc)] = (
        array[max(0, dr):height - max(0, -dr), max(0, dc):width - max(0, -dc)]
    )
    return result


def _flood(candidate, seeds, eight=False):
    """Propaga a partir de sementes sobre a máscara candidate; retorna a região alcançada."""
    reached = seeds & candidate
    height, width = candidate.shape
    queue = deque(zip(*np.nonzero(reached)))
    steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)] if eight else [(-1, 0), (1, 0), (0, -1), (0, 1)]
    while queue:
        r, c = queue.popleft()
        for dr, dc in steps:
            rr, cc = r + dr, c + dc
            if 0 <= rr < height and 0 <= cc < width and candidate[rr, cc] and not reached[rr, cc]:
                reached[rr, cc] = True
                queue.append((rr, cc))
    return reached


def canny_edges(rgb, sigma=1.0, low_ratio=0.4, high_percentile=90.0):
    """Bordas de Canny sobre o maior gradiente Sobel entre canais.

    Retorna (máscara de bordas, magnitude, direção em radianos).
    """
    gx_all, gy_all = [], []
    for channel in range(3):
        gx, gy = sobel_gradients(gaussian_blur(rgb[..., channel], sigma))
        gx_all.append(gx)
        gy_all.append(gy)
    gx_stack, gy_stack = np.stack(gx_all), np.stack(gy_all)
    best = np.argmax(np.hypot(gx_stack, gy_stack), axis=0)
    gx = np.take_along_axis(gx_stack, best[None], axis=0)[0]
    gy = np.take_along_axis(gy_stack, best[None], axis=0)[0]
    magnitude = np.hypot(gx, gy)
    direction = np.arctan2(gy, gx)

    ax, ay = np.abs(gx), np.abs(gy)
    horizontal = ay <= _SECTOR * ax
    vertical = ax <= _SECTOR * ay
    diagonal = ~horizontal & ~vertical
    main = diagonal & (gx * gy > 0)
    first = np.select(
        [horizontal, vertical, main],
        [_shift(magnitude, 0, 1), _shift(magnitude, 1, 0), _shift(magnitude, 1, 1)],
        _shift(magnitude, 1, -1),
    )
    second = np.select(
        [horizontal, vertical, main],
        [_shift(magnitude, 0, -1), _shift(magnitude, -1, 0), _shift(magnitude, -1, -1)],
        _shift(magnitude, -1, 1),
    )
    thin = np.where((magnitude >= first) & (magnitude >= second) & (magnitude > 0), magnitude, 0.0)

    positive = thin[thin > 0]
    if positive.size == 0:
        return np.zeros(thin.shape, dtype=bool), magnitude, direction
    high = float(np.percentile(positive, high_percentile))
    low = low_ratio * high
    strong = thin >= high
    weak = (thin >= low) & (thin > 0)
    edges = _flood(weak, strong, eight=True)
    return edges, magnitude, direction


def color_region(rgb, seed, tolerance, allowed=None, passable=None):
    """Região conectada à semente cuja cor fica dentro da tolerância (máximo entre canais).

    `passable` marca pixels desconhecidos (marcações) que não interrompem a região.
    `allowed` marca pixels proibidos, como sobreposições opacas de outros componentes.
    """
    x, y = seed
    height, width = rgb.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        raise GeometryError("A semente está fora da imagem.")
    patch = rgb[max(0, y - 2):y + 3, max(0, x - 2):x + 3].reshape(-1, 3)
    reference = np.median(patch, axis=0)
    candidate = np.max(np.abs(rgb - reference), axis=2) <= tolerance
    if passable is not None:
        candidate |= passable
    if allowed is not None:
        candidate &= allowed
    if not candidate[y, x]:
        raise GeometryError("A semente não pertence à região de cor dentro da tolerância informada.")
    seeds = np.zeros(candidate.shape, dtype=bool)
    seeds[y, x] = True
    return _flood(candidate, seeds)


def fill_holes(mask):
    """Preenche buracos da máscara: fundo não alcançável pela borda da imagem."""
    background = ~mask
    border = np.zeros(mask.shape, dtype=bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    outside = _flood(background, border & background)
    return ~outside


# --------------------------------------------------------------------------- contornos

def _shoelace(points):
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def trace_loops(mask):
    """Contornos de pixel de uma máscara, em coordenadas de canto.

    Retorna (contornos externos, buracos). Todos os laços usam a mesma orientação,
    então externos e buracos são separados pelo sinal da área.
    """
    padded = np.pad(np.asarray(mask, dtype=bool), 1, constant_values=False)
    outgoing = {}

    def add(start, end):
        outgoing.setdefault(start, []).append(end)

    rows, cols = np.nonzero(mask)
    for r, c in zip(rows.tolist(), cols.tolist()):
        if not padded[r, c + 1]:
            add((c, r), (c + 1, r))
        if not padded[r + 1, c + 2]:
            add((c + 1, r), (c + 1, r + 1))
        if not padded[r + 2, c + 1]:
            add((c + 1, r + 1), (c, r + 1))
        if not padded[r + 1, c]:
            add((c, r + 1), (c, r))

    loops = []
    while outgoing:
        start = next(iter(outgoing))
        points = [start]
        current = start
        while True:
            options = outgoing.get(current)
            if not options:
                raise GeometryError("Contorno de pixels não fechado; a máscara tem topologia inesperada.")
            following = options.pop()
            if not options:
                del outgoing[current]
            if following == start:
                break
            points.append(following)
            current = following
        loops.append(np.array(points, dtype=np.float64))

    if not loops:
        raise GeometryError("A máscara não contém pixels.")
    areas = [_shoelace(loop) for loop in loops]
    dominant = max(range(len(loops)), key=lambda index: abs(areas[index]))
    sign = math.copysign(1.0, areas[dominant])
    outer = [loops[i] for i in range(len(loops)) if math.copysign(1.0, areas[i]) == sign]
    holes = [loops[i] for i in range(len(loops)) if math.copysign(1.0, areas[i]) != sign]
    return outer, holes


def _rdp_open(points, epsilon):
    if len(points) < 3:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        start, end = points[i], points[j]
        segment = end - start
        length = math.hypot(segment[0], segment[1])
        inner = points[i + 1:j] - start
        if length == 0:
            distance = np.hypot(inner[:, 0], inner[:, 1])
        else:
            distance = np.abs(segment[0] * inner[:, 1] - segment[1] * inner[:, 0]) / length
        k = int(np.argmax(distance))
        if distance[k] > epsilon:
            index = i + 1 + k
            keep[index] = True
            stack.append((i, index))
            stack.append((index, j))
    return points[keep]


def simplify_closed(points, epsilon):
    """Douglas–Peucker para contorno fechado (vértices em ordem)."""
    if len(points) < 4 or epsilon <= 0:
        return np.asarray(points, dtype=np.float64)
    distances = np.hypot(*(points - points[0]).T)
    split = int(np.argmax(distances))
    first = _rdp_open(points[:split + 1], epsilon)
    second = _rdp_open(np.vstack([points[split:], points[:1]]), epsilon)
    return np.vstack([first[:-1], second[:-1]])


def resample(points, step=1.0, closed=True):
    """Reamostragem por comprimento de arco com espaçamento aproximado `step`."""
    points = np.asarray(points, dtype=np.float64)
    closing = np.vstack([points, points[:1]]) if closed else points
    lengths = np.hypot(*np.diff(closing, axis=0).T)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    total = cumulative[-1]
    if total <= 0:
        raise GeometryError("Contorno de comprimento zero.")
    count = max(8, int(round(total / step)))
    if closed:
        targets = np.linspace(0.0, total, count, endpoint=False)
    else:
        targets = np.linspace(0.0, total, max(2, count + 1))
    return np.column_stack([
        np.interp(targets, cumulative, closing[:, 0]),
        np.interp(targets, cumulative, closing[:, 1]),
    ])


def bilinear(image, xs, ys):
    """Amostra uma imagem 2D ou HxWxC em coordenadas contínuas, com borda estendida."""
    height, width = image.shape[:2]
    x = np.clip(np.asarray(xs, dtype=np.float64) - 0.5, 0, width - 1)
    y = np.clip(np.asarray(ys, dtype=np.float64) - 0.5, 0, height - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = x - x0
    fy = y - y0
    if image.ndim == 3:
        fx = fx[..., None]
        fy = fy[..., None]
    top = image[y0, x0] * (1 - fx) + image[y0, x1] * fx
    bottom = image[y1, x0] * (1 - fx) + image[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def closed_normals(points, mask=None, smooth=3):
    """Normais unitárias suavizadas; orientadas para dentro da máscara quando ela é dada."""
    tangents = np.roll(points, -1, axis=0) - np.roll(points, 1, axis=0)
    tangents = tangents / np.maximum(np.hypot(tangents[:, 0], tangents[:, 1]), 1e-12)[:, None]
    smoothed = sum(np.roll(tangents, shift, axis=0) for shift in range(-smooth, smooth + 1))
    smoothed = smoothed / np.maximum(np.hypot(smoothed[:, 0], smoothed[:, 1]), 1e-12)[:, None]
    normals = np.column_stack([-smoothed[:, 1], smoothed[:, 0]])
    if mask is not None:
        probe = points + 1.5 * normals
        columns = np.clip(np.floor(probe[:, 0]).astype(int), 0, mask.shape[1] - 1)
        rows = np.clip(np.floor(probe[:, 1]).astype(int), 0, mask.shape[0] - 1)
        if np.mean(mask[rows, columns]) < 0.5:
            normals = -normals
    return normals


def refine_subpixel(gray, points, normals, reach=2.0, step=0.1, max_shift=1.5):
    """Move cada ponto ao cruzamento de 50% entre o interior e o exterior ao longo da normal.

    Retorna (pontos refinados, deslocamento em px, confiança 0–1 por ponto).
    """
    offsets = np.arange(-reach, reach + step / 2, step)
    xs = points[:, 0, None] + offsets[None, :] * normals[:, 0, None]
    ys = points[:, 1, None] + offsets[None, :] * normals[:, 1, None]
    profile = bilinear(gray, xs, ys)
    inner = np.abs(offsets + reach * 0.8) <= reach * 0.2
    outer = np.abs(offsets - reach * 0.8) <= reach * 0.2
    inside = np.median(profile[:, inner], axis=1)
    outside = np.median(profile[:, outer], axis=1)
    contrast = outside - inside
    level = (inside + outside) / 2.0
    sign = np.where(contrast >= 0, 1.0, -1.0)[:, None]
    difference = (profile - level[:, None]) * sign
    crossing = (difference[:, :-1] < 0) & (difference[:, 1:] >= 0)
    found = crossing.any(axis=1)
    first = np.argmax(crossing, axis=1)
    rows = np.arange(len(points))
    d0 = difference[rows, first]
    d1 = difference[rows, first + 1]
    fraction = -d0 / np.where(d1 - d0 == 0, 1e-12, d1 - d0)
    shift = offsets[first] + fraction * step
    usable = found & (np.abs(contrast) >= 4.0)
    shift = np.where(usable, np.clip(shift, -max_shift, max_shift), 0.0)
    confidence = np.where(usable, np.clip(np.abs(contrast) / 40.0, 0.0, 1.0), 0.0)
    refined = points + shift[:, None] * normals
    return refined, shift, confidence


def smooth_closed(points, window=2):
    """Média móvel cíclica para reduzir ruído de quantização."""
    if window <= 0:
        return points
    total = sum(np.roll(points, shift, axis=0) for shift in range(-window, window + 1))
    return total / (2 * window + 1)


def offset_closed(points, normals, distance):
    """Desloca um contorno ao longo de normais (escalar ou vetor por ponto)."""
    distance = np.asarray(distance, dtype=np.float64)
    if distance.ndim == 0:
        distance = np.full(len(points), float(distance))
    return points + distance[:, None] * normals


# --------------------------------------------------------------------------- primitivas

def corner_indices(points, window=3, angle_degrees=35.0):
    """Índices de cantos: mudança de direção maior que o limite numa janela curta."""
    count = len(points)
    index = np.arange(count)
    before = points[(index - window) % count]
    after = points[(index + window) % count]
    first = points - before
    second = after - points
    cross = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    dot = np.sum(first * second, axis=1)
    turn = np.degrees(np.arctan2(np.abs(cross), dot))
    candidates = np.nonzero(turn > angle_degrees)[0]
    if candidates.size == 0:
        return []
    groups = [[int(candidates[0])]]
    for value in candidates[1:].tolist():
        if value - groups[-1][-1] <= window:
            groups[-1].append(value)
        else:
            groups.append([value])
    if len(groups) > 1 and groups[0][0] + count - groups[-1][-1] <= window:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return sorted(max(group, key=lambda i: turn[i]) for group in groups)


def fit_circle(points):
    """Ajuste algébrico de círculo; retorna (cx, cy, r, erro máximo) ou None."""
    x, y = points[:, 0], points[:, 1]
    design = np.column_stack([x, y, np.ones_like(x)])
    solution, *_ = np.linalg.lstsq(design, x * x + y * y, rcond=None)
    cx, cy = solution[0] / 2.0, solution[1] / 2.0
    radius_squared = solution[2] + cx * cx + cy * cy
    if not np.isfinite(radius_squared) or radius_squared <= 0:
        return None
    radius = math.sqrt(radius_squared)
    residual = float(np.max(np.abs(np.hypot(x - cx, y - cy) - radius)))
    return cx, cy, radius, residual


def circle_primitives(cx,cy,radius,fit_error=0.):
    center=np.array([cx,cy],float)
    ends=[center+radius*np.array([math.cos(k*math.pi/2),math.sin(k*math.pi/2)]) for k in range(4)]
    return [{'type':'arc','center':center,'radius':float(radius),'start_angle':k*math.pi/2,
             'sweep':math.pi/2,'start':ends[k],'end':ends[(k+1)%4],'max_error_px':float(fit_error)}
            for k in range(4)]


def _point_segment_distance(points, starts, ends):
    """Distância de cada ponto ao segmento mais próximo; retorna (distância, índice do segmento)."""
    direction = ends - starts
    length_squared = np.maximum(np.sum(direction * direction, axis=1), 1e-12)
    offset = points[:, None, :] - starts[None, :, :]
    t = np.clip(np.sum(offset * direction[None], axis=2) / length_squared[None], 0.0, 1.0)
    closest = starts[None] + t[..., None] * direction[None]
    distance = np.sqrt(np.sum((points[:, None, :] - closest) ** 2, axis=2))
    nearest = np.argmin(distance, axis=1)
    return distance[np.arange(len(points)), nearest], nearest


def _bezier_points(control, count=200):
    t = np.linspace(0.0, 1.0, count)[:, None]
    p0, p1, p2, p3 = control
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


def fit_cubic(points):
    """Cúbica de Bézier com extremos fixos e tangentes livres (método de Schneider)."""
    count = len(points)
    p0, p3 = points[0], points[-1]
    chord = math.hypot(*(p3 - p0))
    lengths = np.hypot(*np.diff(points, axis=0).T)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    u = cumulative / cumulative[-1] if cumulative[-1] > 0 else np.linspace(0.0, 1.0, count)
    # Direções das tangentes pelos vizinhos imediatos; os comprimentos das alças são resolvidos
    # por mínimos quadrados, e os parâmetros das amostras são refinados até estabilizar.
    t1 = points[min(count - 1, 1)] - p0
    t2 = points[max(0, count - 2)] - p3
    t1 = t1 / max(math.hypot(*t1), 1e-12)
    t2 = t2 / max(math.hypot(*t2), 1e-12)
    grid = np.linspace(0.0, 1.0, 400)
    control = None
    for _ in range(12):
        b0 = (1 - u) ** 3
        b1 = 3 * u * (1 - u) ** 2
        b2 = 3 * u * u * (1 - u)
        b3 = u ** 3
        a1 = t1[None, :] * b1[:, None]
        a2 = t2[None, :] * b2[:, None]
        c00 = float(np.sum(a1 * a1))
        c01 = float(np.sum(a1 * a2))
        c11 = float(np.sum(a2 * a2))
        residual = points - (p0[None] * (b0 + b1)[:, None] + p3[None] * (b2 + b3)[:, None])
        x0 = float(np.sum(a1 * residual))
        x1 = float(np.sum(a2 * residual))
        determinant = c00 * c11 - c01 * c01
        alpha_left = alpha_right = chord / 3.0
        if abs(determinant) > 1e-12:
            candidate_left = (x0 * c11 - c01 * x1) / determinant
            candidate_right = (c00 * x1 - c01 * x0) / determinant
            if candidate_left > 1e-6 * chord and candidate_right > 1e-6 * chord:
                alpha_left, alpha_right = candidate_left, candidate_right
        p1 = p0 + t1 * alpha_left
        p2 = p3 + t2 * alpha_right
        previous = control
        control = np.array([p0, p1, p2, p3], dtype=np.float64)
        if previous is not None and np.max(np.abs(control - previous)) < 1e-6:
            break
        # Reparametrização: cada amostra recebe o parâmetro do ponto mais próximo da curva atual.
        curve = _bezier_points(control, count=grid.size)
        nearest = np.argmin(np.hypot(points[:, None, 0] - curve[None, :, 0], points[:, None, 1] - curve[None, :, 1]), axis=1)
        u = grid[nearest]
        u[0], u[-1] = 0.0, 1.0
    return control


def _fit_cubic_recursive(points, tolerance, depth=0):
    control = fit_cubic(points)
    curve = _bezier_points(control)
    distance, _ = _point_segment_distance(points, curve[:-1], curve[1:])
    error = float(distance.max())
    if error <= tolerance or depth >= 6 or len(points) < 8:
        return [{"type": "cubic", "control": control, "max_error_px": error}]
    split = int(np.argmax(distance))
    split = min(max(split, 3), len(points) - 4)
    return (_fit_cubic_recursive(points[:split + 1], tolerance, depth + 1)
            + _fit_cubic_recursive(points[split:], tolerance, depth + 1))


def _fit_run(run, tolerance):
    start, end = run[0], run[-1]
    if len(run) < 3:
        return [{"type": "line", "start": start, "end": end, "max_error_px": 0.0}]
    chord_direction = end - start
    chord_length = math.hypot(chord_direction[0], chord_direction[1])
    if chord_length > 0:
        offset = run - start
        perpendicular = np.abs(chord_direction[0] * offset[:, 1] - chord_direction[1] * offset[:, 0]) / chord_length
        line_error = float(perpendicular.max())
    else:
        line_error = float(np.hypot(*(run - start).T).max())
    if line_error <= tolerance:
        return [{"type": "line", "start": start, "end": end, "max_error_px": line_error}]
    circle = fit_circle(run)
    if circle is not None and circle[3] <= tolerance:
        cx, cy, radius, residual = circle
        angles = np.unwrap(np.arctan2(run[:, 1] - cy, run[:, 0] - cx))
        sweep = float(angles[-1] - angles[0])
        if abs(sweep) >= math.radians(20) and radius < 1e5:
            return [{
                "type": "arc", "start": start, "end": end, "center": np.array([cx, cy]),
                "radius": radius, "start_angle": float(angles[0]), "sweep": sweep,
                "max_error_px": residual,
            }]
    return _fit_cubic_recursive(run, tolerance)


def fit_primitives(points, tolerance=0.6, corner_degrees=35.0):
    """Ajusta retas, arcos e cúbicas de Bézier a um contorno fechado.

    Cantos com mudança de direção acima de `corner_degrees` são preservados como vértices.
    Contornos suaves sem canto são divididos em quatro trechos para permitir arcos e círculos.
    """
    dense = resample(points, step=1.0, closed=True)
    circle=fit_circle(dense)
    if circle is not None and circle[3]<=tolerance:
        return circle_primitives(*circle[:3],fit_error=circle[3])
    # Preserve vértices já ajustados: reamostrar e procurar só picos locais
    # arredondava chanfros e convertia polígonos inteiros em Béziers.
    candidate = simplify_closed(np.asarray(points), tolerance)
    if 3 <= len(candidate) <= 16:
        first = candidate-np.roll(candidate, 1, axis=0)
        second = np.roll(candidate, -1, axis=0)-candidate
        angles = np.degrees(np.arctan2(np.abs(first[:,0]*second[:,1]-first[:,1]*second[:,0]),
                                      np.sum(first*second, axis=1)))
        if np.min(angles) >= 25:
            distance, _ = _point_segment_distance(dense, candidate, np.roll(candidate,-1,axis=0))
            if distance.max() <= tolerance:
                return [{'type':'line', 'start':a, 'end':b, 'max_error_px':float(distance.max())}
                        for a,b in zip(candidate,np.roll(candidate,-1,axis=0))]
    count = len(dense)
    corners = corner_indices(dense, angle_degrees=corner_degrees)
    if len(corners) < 2:
        corners = sorted({int(round(k * count / 4.0)) % count for k in range(4)})
    segments = []
    for k, start in enumerate(corners):
        end = corners[(k + 1) % len(corners)]
        if end > start:
            run = dense[start:end + 1]
        else:
            run = np.vstack([dense[start:], dense[:end + 1]])
        segments.extend(_fit_run(run, tolerance))
    return segments


def fit_open_primitives(points, tolerance=0.6):
    """Ajuste aberto: reta, quadrática ou cúbicas, sem inventar uma aresta de fechamento."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
        raise GeometryError('Um caminho aberto exige ao menos dois pontos finitos [x,y].')
    start, end = points[0], points[-1]
    distance, _ = _point_segment_distance(points, start[None], end[None])
    if distance.max() <= tolerance:
        return [{'type': 'line', 'start': start, 'end': end, 'max_error_px': float(distance.max())}]
    # Reparametrização numérica da quadrática, com extremos fixos.
    u = np.linspace(0, 1, len(points))
    grid = np.linspace(0, 1, 800)
    for _ in range(20):
        basis = 2*u*(1-u)
        residual = points - (1-u)[:, None]**2*start - u[:, None]**2*end
        middle = (basis[:, None]*residual).sum(axis=0) / max(float(basis@basis), 1e-12)
        curve = (1-grid)[:, None]**2*start + (2*grid*(1-grid))[:, None]*middle + grid[:, None]**2*end
        nearest = np.argmin(np.sum((points[:, None]-curve[None])**2, axis=2), axis=1)
        u = grid[nearest]
        u[0], u[-1] = 0, 1
    error, _ = _point_segment_distance(points, curve[:-1], curve[1:])
    if error.max() <= tolerance:
        return [{'type': 'quadratic', 'control': np.array([start, middle, end]), 'max_error_px': float(error.max())}]
    return _fit_cubic_recursive(points, tolerance)


def sample_segments(segments, step=0.5):
    """Amostra os primitivos num polígono fechado denso (para renderização e métricas)."""
    pieces = []
    for segment in segments:
        if segment["type"] == "line":
            start, end = segment["start"], segment["end"]
            length = max(math.hypot(*(end - start)), 1e-9)
            count = max(2, int(math.ceil(length / step)))
            t = np.linspace(0.0, 1.0, count, endpoint=False)[:, None]
            pieces.append(start + t * (end - start))
        elif segment["type"] == "arc":
            center, radius = segment["center"], segment["radius"]
            length = abs(segment["sweep"]) * radius
            count = max(4, int(math.ceil(length / step)))
            angles = segment["start_angle"] + np.linspace(0.0, segment["sweep"], count, endpoint=False)
            pieces.append(np.column_stack([center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)]))
        elif segment['type'] == 'quadratic':
            t = np.linspace(0, 1, 200)[:, None]
            p0, p1, p2 = segment['control']
            pieces.append(((1-t)**2*p0 + 2*(1-t)*t*p1 + t*t*p2)[:-1])
        else:
            pieces.append(_bezier_points(segment["control"], count=200)[:-1])
    return np.vstack(pieces) if pieces else np.zeros((0, 2))


def segments_length(segments):
    """Comprimento aproximado do contorno representado por primitivos."""
    return float(np.sum(np.hypot(*np.diff(sample_segments(segments, 0.25), axis=0).T)))


# --------------------------------------------------------------------------- campos de distância

def signed_distance(polygon, shape, spacing=0.5, chunk=4096):
    """Distância assinada em pixels (negativa dentro) a um polígono fechado.

    Distância exata aos segmentos da polilinha fornecida, não às amostras isoladas.
    Para curvas, a aproximação é a discretização explícita de sample_segments.
    A paridade decide o interior. spacing/chunk são mantidos por compatibilidade.
    """
    height, width = shape
    rows, columns = np.mgrid[0:height, 0:width]
    px = columns.ravel() + 0.5
    py = rows.ravel() + 0.5
    vertices = np.asarray(polygon, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or len(vertices) < 3 or not np.isfinite(vertices).all():
        raise GeometryError('SDF assinado exige polígono fechado com ao menos três vértices finitos.')
    distance_squared = np.full(px.shape, np.inf)
    # Um vetor por aresta: memória O(pixels), sem matriz pixels × amostras.
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        direction = b-a
        denominator = float(direction@direction)
        t = np.clip(((px-a[0])*direction[0] + (py-a[1])*direction[1])/max(denominator, 1e-20), 0, 1)
        candidate = (px-a[0]-t*direction[0])**2 + (py-a[1]-t*direction[1])**2
        np.minimum(distance_squared, candidate, out=distance_squared)
    inside = np.zeros(px.shape, dtype=bool)
    starts = vertices
    ends = np.roll(vertices, -1, axis=0)
    for (x0, y0), (x1, y1) in zip(starts, ends):
        if y0 == y1:
            continue
        crosses = (y0 > py) != (y1 > py)
        x_at = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (px < x_at)
    signed = np.where(inside, -np.sqrt(distance_squared), np.sqrt(distance_squared))
    return signed.reshape(height, width)


def coverage_from_distance(signed):
    """Cobertura antialias de 1 px a partir da distância assinada."""
    return np.clip(0.5 - signed, 0.0, 1.0)


def unsigned_distance(points, shape):
    """Distância a uma polilinha aberta, sem segmento de fechamento ou sinal inventado."""
    points=np.asarray(points,float)
    if len(points)<2 or not np.isfinite(points).all():
        raise GeometryError('Distância aberta exige ao menos dois pontos finitos.')
    rows,cols=np.mgrid[:shape[0],:shape[1]]
    x,y=cols+0.5,rows+0.5
    result=np.full(shape,np.inf)
    for a,b in zip(points[:-1],points[1:]):
        d=b-a
        t=np.clip(((x-a[0])*d[0]+(y-a[1])*d[1])/max(float(d@d),1e-12),0,1)
        np.minimum(result,(x-a[0]-t*d[0])**2+(y-a[1]-t*d[1])**2,out=result)
    return np.sqrt(result)


def _color_field(fill, shape):
    height, width = shape
    if isinstance(fill, dict):
        rows, columns = np.mgrid[0:height, 0:width]
        origin = np.asarray(fill["origin"], dtype=np.float64)
        slope = np.asarray(fill["slope"], dtype=np.float64)
        dx = columns + 0.5 - origin[0]
        dy = rows + 0.5 - origin[1]
        base = np.asarray(fill["color"], dtype=np.float64)
        return np.clip(base[None, None, :] + dx[..., None] * slope[0][None, None, :] + dy[..., None] * slope[1][None, None, :], 0, 255)
    color = np.asarray(fill, dtype=np.float64)
    return np.broadcast_to(color, (height, width, 3))


def render_layers(shape, layers):
    """Compõe camadas em RGBA premultiplicado sobre transparência e retorna RGBA 0–255.

    Cada camada: {"kind": "fill", "polygon", "fill", "opacity"} ou
    {"kind": "glow", "polygon", "color", "amplitude", "sigma"}.
    """
    height, width = shape
    premultiplied = np.zeros((height, width, 3))
    alpha = np.zeros((height, width))
    for layer in layers:
        signed = signed_distance(layer["polygon"], shape)
        for hole in layer.get('holes', []):
            signed = np.maximum(signed, -signed_distance(hole, shape))
        if layer["kind"] == "glow":
            outside = np.maximum(signed, 0.0)
            coverage = layer["amplitude"] * np.exp(-outside * outside / (2 * layer["sigma"] ** 2))
            color = np.broadcast_to(np.asarray(layer["color"], dtype=np.float64), (height, width, 3))
        else:
            coverage = coverage_from_distance(signed) * layer.get("opacity", 1.0)
            color = _color_field(layer["fill"], shape)
        coverage = np.clip(coverage, 0.0, 1.0)
        keep = 1.0 - coverage
        premultiplied = premultiplied * keep[..., None] + color * coverage[..., None]
        alpha = alpha * keep + coverage
    rgb = np.where(alpha[..., None] > 1e-9, premultiplied / np.maximum(alpha[..., None], 1e-9), 0.0)
    return np.dstack([np.clip(rgb, 0, 255), alpha * 255.0])


# --------------------------------------------------------------------------- otimização

def levenberg_marquardt(residuals, x0, max_iterations=60, tolerance=1e-4, step=1e-3):
    """Mínimos quadrados não lineares (Levenberg–Marquardt) com Jacobiano numérico.

    `residuals(x)` deve retornar vetor de tamanho fixo. Retorna (x, histórico de custo).
    """
    x = np.asarray(x0, dtype=np.float64).copy()
    current = residuals(x)
    cost = float(current @ current)
    history = [cost]
    damping = 1e-2
    for _ in range(max_iterations):
        jacobian = np.empty((current.size, x.size))
        for index in range(x.size):
            bumped = x.copy()
            bumped[index] += step
            jacobian[:, index] = (residuals(bumped) - current) / step
        normal = jacobian.T @ jacobian
        gradient = jacobian.T @ current
        improved = False
        for _ in range(12):
            system = normal + damping * np.diag(np.maximum(np.diag(normal), 1e-9))
            delta = -np.linalg.solve(system, gradient)
            candidate = x + delta
            candidate_residual = residuals(candidate)
            candidate_cost = float(candidate_residual @ candidate_residual)
            if candidate_cost < cost:
                x, current, cost = candidate, candidate_residual, candidate_cost
                damping = max(damping / 3.0, 1e-7)
                improved = True
                break
            damping *= 4.0
        history.append(cost)
        if not improved or float(np.max(np.abs(delta))) < tolerance:
            break
    return x, history


def chamfer_residuals(model_samples, evidence, weight=1.0):
    """Distâncias do modelo ao suporte observado e vice-versa, como vetor de resíduos."""
    to_evidence = nearest_distances(model_samples, evidence)
    to_model = nearest_distances(evidence, model_samples)
    return weight * np.concatenate([to_evidence, to_model])


def fit_polygon_vertices(vertices, evidence, *, anchor_weight=0.05, contour_weight=1.0, spacing=0.8, max_iterations=60, known_mask=None):
    """Refina vértices de um polígono fechado por Chamfer bidirecional com ancoragem.

    Cada aresta é amostrada a cada `spacing` px (contagem fixa, definida pela geometria inicial),
    para que a distância do modelo à evidência não seja dominada por lacunas de amostragem.
    Retorna (vértices refinados, histórico de custo, distâncias finais do modelo à evidência).
    """
    initial = np.asarray(vertices, dtype=np.float64)
    # Ajuste ortogonal das partes retilíneas e interseção das retas:
    # centros de pixels antialias próximos do canto não são o vértice geométrico.
    first=initial-np.roll(initial,1,axis=0)
    second=np.roll(initial,-1,axis=0)-initial
    turns=np.degrees(np.arctan2(np.abs(first[:,0]*second[:,1]-first[:,1]*second[:,0]),np.sum(first*second,axis=1)))
    if 3<len(initial)<=16 and np.mean(turns>=25)>=0.7:
        # Remova somente quinas quase colineares de um modelo já predominantemente
        # poligonal. Isso não transforma uma curva suave em um triângulo.
        while len(initial)>3:
            a=initial-np.roll(initial,1,axis=0)
            b=np.roll(initial,-1,axis=0)-initial
            turns=np.degrees(np.arctan2(np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]),np.sum(a*b,axis=1)))
            if turns.min()>=25:
                break
            initial=np.delete(initial,int(np.argmin(turns)),axis=0)
        first=initial-np.roll(initial,1,axis=0)
        second=np.roll(initial,-1,axis=0)-initial
        turns=np.degrees(np.arctan2(np.abs(first[:,0]*second[:,1]-first[:,1]*second[:,0]),np.sum(first*second,axis=1)))
    if 3<=len(initial)<=16 and turns.min()>=25:
        ends=np.roll(initial,-1,axis=0)
        _,assignment=_point_segment_distance(evidence,initial,ends)
        lines=[]
        for i,(a,b) in enumerate(zip(initial,ends)):
            direction=b-a
            t=((evidence-a)@direction)/max(float(direction@direction),1e-12)
            selected=evidence[(assignment==i)&(t>0.12)&(t<0.88)]
            if len(selected)>=4:
                center=selected.mean(axis=0)
                _,_,vh=np.linalg.svd(selected-center,full_matrices=False)
                lines.append((center,vh[0]))
            else:
                lines.append((a,direction))
        candidate=[]
        for i,(center,direction) in enumerate(lines):
            before,vector=lines[i-1]
            matrix=np.column_stack([vector,-direction])
            if abs(np.linalg.det(matrix))<1e-8:
                candidate.append(initial[i])
            else:
                value=np.linalg.solve(matrix,center-before)
                candidate.append(before+value[0]*vector)
        candidate=np.array(candidate)
        errors,_=_point_segment_distance(evidence,candidate,np.roll(candidate,-1,axis=0))
        if np.quantile(errors,.9)<0.65 and np.max(np.linalg.norm(candidate-initial,axis=1))<4:
            return candidate,[float(np.sum(errors**2)),float(np.sum(errors**2))],errors
    count = len(initial)
    lengths = np.hypot(*(np.roll(initial, -1, axis=0) - initial).T)
    per_edge = np.maximum(2, np.ceil(lengths / spacing).astype(int))
    fractions = [np.linspace(0.0, 1.0, k, endpoint=False)[:, None] for k in per_edge]

    def model_samples(flat):
        current = flat.reshape(count, 2)
        ends = np.roll(current, -1, axis=0)
        return np.vstack([current[i] + fractions[i] * (ends[i] - current[i]) for i in range(count)])

    def residuals(flat):
        samples = model_samples(flat)
        chamfer = chamfer_residuals(samples, evidence, contour_weight)
        if known_mask is not None:
            rows=np.clip(np.floor(samples[:,1]).astype(int),0,known_mask.shape[0]-1)
            cols=np.clip(np.floor(samples[:,0]).astype(int),0,known_mask.shape[1]-1)
            chamfer[:len(samples)] *= known_mask[rows,cols]
        anchor = anchor_weight * (flat - initial.ravel())
        return np.concatenate([chamfer, anchor])

    solution, history = levenberg_marquardt(residuals, initial.ravel(), max_iterations=max_iterations)
    refined = solution.reshape(count, 2)
    final = nearest_distances(model_samples(solution), evidence)
    if known_mask is not None:
        samples=model_samples(solution)
        rows=np.clip(np.floor(samples[:,1]).astype(int),0,known_mask.shape[0]-1)
        cols=np.clip(np.floor(samples[:,0]).astype(int),0,known_mask.shape[1]-1)
        final=final[known_mask[rows,cols]]
    return refined, history, final


def bidirectional_chamfer(model_points, evidence):
    """Métrica geométrica entre dois conjuntos de pontos (px)."""
    to_evidence = nearest_distances(model_points, evidence)
    to_model = nearest_distances(evidence, model_points)
    return {
        "mean_model_to_evidence_px": float(to_evidence.mean()),
        "mean_evidence_to_model_px": float(to_model.mean()),
        "bidirectional_mean_px": float((to_evidence.mean() + to_model.mean()) / 2.0),
        "hausdorff_px": float(max(to_evidence.max(), to_model.max())),
        "to_evidence": to_evidence,
        "to_model": to_model,
    }


def ssim_luminance(reference, actual, window=7):
    """SSIM médio de janela uniforme sobre luminância (0–255), sem recorte de borda."""
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_x = box_filter(reference, window)
    mu_y = box_filter(actual, window)
    sigma_x = box_filter(reference * reference, window) - mu_x * mu_x
    sigma_y = box_filter(actual * actual, window) - mu_y * mu_y
    sigma_xy = box_filter(reference * actual, window) - mu_x * mu_y
    value = ((2 * mu_x * mu_y + c1) * (2 * sigma_xy + c2)) / ((mu_x ** 2 + mu_y ** 2 + c1) * (sigma_x + sigma_y + c2))
    margin = window // 2 + 1
    return value[margin:-margin, margin:-margin]
