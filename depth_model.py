"""原画的连续部位网格、跟随与柔光。只有 PIL,不读取配置或存档。"""
import math
from collections import OrderedDict
from PIL import Image, ImageDraw, ImageFilter


def clamp(x, lo=-1., hi=1.):
    return max(lo, min(hi, x))


class DepthMotion:
    """独立的有限状态,按真实经过时间平滑,不安排延迟回调。"""
    BLOCKED = frozenset(('flip', 'roll', 'twirl', 'rewind', 'fly'))

    def __init__(self):
        self.last = None
        self.values = [0.] * 6  # head x/y, body x/y, hair x/y
        self.blocked = False
        self.recovered = None

    def sample(self, now, x, y, state='idle', dragging=False):
        dt = max(0., now-self.last) if self.last is not None else 0.
        self.last = now
        x, y = clamp(x), clamp(y)
        if state in ('sleep', 'yawn'):
            x = y = 0.
        for index, tau in enumerate((.12, .20, .26)):
            blend = -math.expm1(-min(dt, 5.)/tau)
            for axis, target in enumerate((x, y)):
                slot = index*2+axis
                self.values[slot] += (target-self.values[slot])*blend
        blocked = state in self.BLOCKED
        if self.blocked and not blocked:
            self.recovered = now
        self.blocked = blocked
        gain = .35 if dragging else 1.
        if blocked:
            gain = 0.
        elif self.recovered is not None:
            phase = clamp((now-self.recovered)/.25, 0., 1.)
            gain *= phase*phase*(3-2*phase)
        return tuple(v*gain for v in self.values)


class DepthWarp:
    """共用一张连续采样网格,部位是软权重而非独立切开的贴片。"""
    # 归一化原画区域;外围边框、小动物和星纹保持不动。
    REGIONS = {
        'hat': ((.08,.09),(.24,.07),(.46,.18),(.67,.02),(.66,.23),
                (.82,.39),(.94,.47),(.92,.54),(.70,.46),(.37,.29),(.17,.26)),
        'hair': ((.33,.27),(.51,.28),(.65,.39),(.70,.56),(.60,.63),
                 (.27,.63),(.26,.45)),
        'face': ((.33,.46),(.59,.44),(.64,.53),(.57,.59),(.40,.60),(.30,.55)),
        'body': ((.44,.57),(.57,.58),(.63,.52),(.69,.51),(.65,.64),
                 (.56,.72),(.40,.72),(.37,.64)),
        'skirt': ((.40,.67),(.57,.66),(.74,.70),(.87,.80),(.66,.83),
                  (.67,.96),(.61,.99),(.51,.94),(.47,.81),(.29,.94),(.25,.87)),
        'broom': ((.02,.81),(.27,.86),(.62,.67),(.91,.52),(.97,.57),
                  (.86,.74),(.62,.75),(.28,.93),(.07,.91)),
    }

    def __init__(self, img):
        self.img = img
        self.w, self.h = img.size
        self.gx, self.gy = 14, 18
        # 顶点与目标格子使用同一整数边界,避免非整除尺寸的单像素接缝。
        self.gxs = [round(self.w*i/self.gx) for i in range(self.gx+1)]
        self.gys = [round(self.h*j/self.gy) for j in range(self.gy+1)]
        self.pivot_y = self.h*.86
        self.masks = {}
        for name, points in self.REGIONS.items():
            mask = Image.new('L', (96, 96))
            ImageDraw.Draw(mask).polygon([(round(x*95),round(y*95)) for x,y in points], fill=255)
            self.masks[name] = mask.filter(ImageFilter.GaussianBlur(2.0))
        self.weights = [[self.region_weights(x/self.w, y/self.h)
                         for x in self.gxs] for y in self.gys]
        self._light_cache = OrderedDict()
        self._mesh_key = None
        self._mesh = None
        self._shadow_cache = OrderedDict()
        self._light_fields = [self._gain_fields(x/23,y/23)
                              for y in range(24) for x in range(24)]
        # 两张固定亮度端点,档位变化只需灰度遮罩合成。
        rgb = img.convert('RGB')
        alpha = img.getchannel('A')
        self._light_low = rgb.point([round(v*.92) for v in range(256)]*3).convert('RGBA')
        self._light_high = rgb.point([min(255,round(v*1.08)) for v in range(256)]*3).convert('RGBA')
        self._light_low.putalpha(alpha)
        self._light_high.putalpha(alpha)
        # 透明区覆盖积分图:先二值化再 reduce,一根细发丝也不会被漏掉。
        coverage = img.getchannel('A').point(lambda a:255 if a else 0).reduce(8)
        self._cover_w, self._cover_h = coverage.size
        self._cover = [[0]*(self._cover_w+1)]
        pixels = coverage.tobytes()
        for y in range(self._cover_h):
            row, acc = [0], 0
            for x in range(self._cover_w):
                acc += bool(pixels[y*self._cover_w+x])
                row.append(acc+self._cover[-1][x+1])
            self._cover.append(row)

    def region_weights(self, x, y):
        ix, iy = round(clamp(x,0,1)*95), round(clamp(y,0,1)*95)
        raw = {n:m.getpixel((ix,iy))/255 for n,m in self.masks.items()}
        # 脸优先,保证双眼与嘴是同一个刚性较强的区域。
        result, remaining = {}, 1.
        for name in ('face','body','hair','hat','skirt','broom'):
            result[name] = raw[name]*remaining
            remaining *= 1-raw[name]
        # 装饰星在帽檐上,也不跟着人物产生额外深度变化。
        star = ((x-.74)/.075)**2+((y-.315)/.055)**2
        protect = clamp((star-.6)/.7,0,1)
        return tuple(result[n]*protect for n in self.REGIONS)

    def _coefficients(self, pose):
        hx, hy, bx, by, fx, fy = pose
        result = []
        for name, depth in zip(self.REGIONS,(.11,.12,.15,.07,.06,.025)):
            head = name in ('hat','hair','face')
            yaw = math.radians(8)*(hx if head else bx)
            pitch = math.radians(4)*(hy if head else by)
            center_x, center_y = (.48,.51) if head else (.5,.74)
            ax = math.cos(yaw)-1-math.sin(yaw)*.045
            ay = math.cos(pitch)-1
            ox = math.sin(yaw)*depth*self.w-ax*center_x*self.w
            oy = math.sin(pitch)*depth*self.h*.6-ay*center_y*self.h
            if name in ('hat','hair'):
                ox += clamp(fx-hx)*self.w*.015
                oy += clamp(fy-hy)*self.h*.0075
            result.append((ax,ox,ay,oy))
        return result

    def displacement(self, x, y, weights, pose, lean, squash, bend, bob=0, coefficients=None):
        coefficients = coefficients if coefficients is not None else self._coefficients(pose)
        total = sum(weights)
        ar = (self.pivot_y-y)/self.h
        dx = (-math.tan(clamp(lean,-.5,.5))*.5*(y-self.pivot_y)
              + bend*.22*self.w*ar*ar)*total
        dy = -bob*total
        sq = clamp(squash,.6,1.4)
        dx += (x-self.w/2)*(sq-1)*total
        dy += (self.pivot_y-y)*(1/sq-1)*total
        for weight, (ax,ox,ay,oy) in zip(weights,coefficients):
            if not weight:
                continue
            # 温和的近远侧压缩,脸上不使用逐像素起伏,避免拉扯五官。
            dx += weight*(ax*x+ox)
            dy += weight*(ay*y+oy)
        return dx, dy

    def mesh(self, pose, lean=0., squash=1., bend=0., bob=0.):
        pose = tuple(clamp(v) for v in pose)
        key = (pose, lean, squash, bend, bob)
        if key == self._mesh_key:
            return self._mesh
        coefficients = self._coefficients(pose)
        rows = [[self.displacement(x,y,self.weights[j][i],pose,lean,squash,bend,bob,coefficients)
                 for i,x in enumerate(self.gxs)] for j,y in enumerate(self.gys)]
        # 极端主动作叠加时统一减小位移,相邻格子始终共边且不翻折。
        # 仅限制变形,不改变动作时长、落点或原画透明度。
        gain = 1.
        for attempt in range(18):
            data, valid = [], True
            for j in range(self.gy):
                for i in range(self.gx):
                    quad = []
                    for a,b in ((i,j),(i,j+1),(i+1,j+1),(i+1,j)):
                        dx,dy = rows[b][a]
                        quad.extend((self.gxs[a]-dx*gain,self.gys[b]-dy*gain))
                    pts = list(zip(quad[::2],quad[1::2]))
                    for v in range(4):
                        a,b,c = pts[v],pts[(v+1)%4],pts[(v+2)%4]
                        if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) >= -.01:
                            valid = False
                    data.append(((self.gxs[i],self.gys[j],self.gxs[i+1],self.gys[j+1]),tuple(quad)))
            if valid:
                break
            gain *= .75
        self._mesh_key, self._mesh = key, data
        return data

    def _gain_fields(self, x, y):
        weights = dict(zip(self.REGIONS,self.region_weights(x,y)))
        face = weights['face']
        material = sum(weights.values())
        # 左上主光,轻微起伏+交界暗部;不对背景装饰染色。
        shape = (.52-x)*.07 + (.55-y)*.025
        seam = -.018*math.exp(-((y-.445)/.045)**2)*weights['hair']
        limit = .08*(1-face)+.04*face
        return shape*material+seam, -(x-.48)*.22*material, -(y-.55)*.06*material, limit

    def light_gain(self, x, y, yaw, pitch):
        base,dx,dy,limit = self._gain_fields(x,y)
        return 1+clamp(base+yaw*dx+pitch*dy,-limit,limit)

    def lit_source(self, pose):
        key = (round(clamp(pose[0])*4),round(clamp(pose[1])*2))
        cached = self._light_cache.get(key)
        if cached is not None:
            self._light_cache.move_to_end(key)
            return cached
        # 小图计算与大图像素运算仅在光照档位改变时发生。
        changes = [clamp(base+key[0]/4*dx+key[1]/2*dy,-limit,limit)
                   for base,dx,dy,limit in self._light_fields]
        dark,bright = Image.new('L',(24,24)),Image.new('L',(24,24))
        dark.putdata([round(max(0,-v)*255/.08) for v in changes])
        bright.putdata([round(max(0,v)*255/.08) for v in changes])
        # 分别从原色向亮/暗端点混合,饱和白色在中立光照下也不会被压灰。
        dark = dark.resize(self.img.size,Image.Resampling.BILINEAR)
        bright = bright.resize(self.img.size,Image.Resampling.BILINEAR)
        lit = Image.composite(self._light_low,self.img,dark)
        lit = Image.composite(self._light_high,lit,bright)
        self._light_cache[key] = lit
        while len(self._light_cache)>2:
            self._light_cache.popitem(last=False)
        return lit

    def _has_ink(self, quad):
        xs,ys = quad[::2],quad[1::2]
        left = max(0,min(self._cover_w,math.floor((min(xs)-2)/8)))
        right = max(0,min(self._cover_w,math.ceil((max(xs)+2)/8)))
        top = max(0,min(self._cover_h,math.floor((min(ys)-2)/8)))
        bottom = max(0,min(self._cover_h,math.ceil((max(ys)+2)/8)))
        sums = self._cover
        return sums[bottom][right]-sums[top][right]-sums[bottom][left]+sums[top][left]>0

    def warp(self, look_x, look_y, lean_rad, bob, squash, amp, bend=0.,
             *, pose=None, source=None, lighting=True, source_alpha_fixed=False):
        pose = pose if pose is not None else (look_x,look_y)*3
        skip_clear = source is None or source_alpha_fixed
        source = source if source is not None else self.lit_source(pose) if lighting else self.img
        mesh = self.mesh(pose,lean_rad,squash,bend,bob)
        if skip_clear:
            mesh = [(box,q) for box,q in mesh if self._has_ink(q)]
        return source.transform(source.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)

    def shadow(self, height, scale=1):
        level = round(clamp(height/max(1,150*scale),0,1)*12)
        if level in self._shadow_cache:
            return self._shadow_cache[level]
        phase = level/12
        w,h = round(self.w*(.40+.18*phase)), max(8,round(self.h*.08))
        im = Image.new('RGBA',(w,h))
        ImageDraw.Draw(im).ellipse((w*.05,h*.3,w*.95,h*.7),fill=(32,23,48,round(42*(1-phase))))
        im = im.filter(ImageFilter.GaussianBlur(max(1,h*.13)))
        self._shadow_cache[level] = im
        return im
