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
    # 原画上的部位几何(归一化):换立绘时由 pet.py 按 assets/config.json 的
    # "rig" 覆盖。默认值 = 旧立绘,测试用的合成图也按这套。
    #   regions 部位多边形(顺序固定:帽/发/脸/身/裙/第六区,displacement 按下标取)
    #   pivot_y 倾斜/挤压支点;head_c/body_c 头、身转动中心;star 帽檐星饰保护椭圆
    #   hat_base_y/hat_pivot_x 帽子摆动的帽基;hair_y0/hair_top 发梢摆动带;
    #   skirt_y0/skirt_span 裙摆拖尾带;breath_c 胸口;light_c 主光零点;seam_y 刘海阴影线
    RIG_DEFAULT = {
        'regions': None, 'pivot_y': .86, 'head_c': (.48, .51), 'body_c': (.5, .74),
        'star': (.74, .315, .075, .055), 'hat_base_y': .34, 'hat_pivot_x': .44,
        'hair_y0': .40, 'hair_top': .62, 'skirt_y0': .66, 'skirt_span': .30,
        'breath_c': (.50, .60), 'light_c': (.52, .55), 'seam_y': .445,
        'light_dc': (.48, .55),
    }

    def __init__(self, img, rig=None):
        self.img = img
        self.w, self.h = img.size
        r = dict(self.RIG_DEFAULT)
        r.update({k: v for k, v in (rig or {}).items() if k in r})
        self.rig = r
        # 部位多边形:实例自己的一份(新立绘的 rig 可以整套替换);
        # 名字和顺序不能变 —— displacement 里按下标 0=帽 2=发 3=身 4=裙 取权重
        self.regions = dict(self.REGIONS)
        for name, pts in (r['regions'] or {}).items():
            if name in self.regions:
                self.regions[name] = tuple(tuple(p) for p in pts)
        self.gx, self.gy = 18, 24   # 身体形变通道增多,加密网格防拉扯
        # 顶点与目标格子使用同一整数边界,避免非整除尺寸的单像素接缝。
        self.gxs = [round(self.w*i/self.gx) for i in range(self.gx+1)]
        self.gys = [round(self.h*j/self.gy) for j in range(self.gy+1)]
        self.pivot_y = self.h*r['pivot_y']
        self.masks = {}
        for name, points in self.regions.items():
            mask = Image.new('L', (96, 96))
            ImageDraw.Draw(mask).polygon([(round(x*95),round(y*95)) for x,y in points], fill=255)
            self.masks[name] = mask.filter(ImageFilter.GaussianBlur(2.0))
        self.weights = [[self.region_weights(x/self.w, y/self.h)
                         for x in self.gxs] for y in self.gys]
        self._light_cache = OrderedDict()
        self._layer_light_cache = OrderedDict()   # 分层图的光照版本(Live2D 层同步)
        self._premul_cache = OrderedDict()   # 源图 -> 预乘(RGBa)版,见 _premultiplied
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
        sx, sy, srx, sry = self.rig['star']
        star = ((x-sx)/srx)**2+((y-sy)/sry)**2
        protect = clamp((star-.6)/.7,0,1)
        return tuple(result[n]*protect for n in self.REGIONS)

    def _coefficients(self, pose):
        hx, hy, bx, by, fx, fy = pose
        result = []
        for name, depth in zip(self.REGIONS,(.11,.12,.15,.07,.06,.025)):
            head = name in ('hat','hair','face')
            yaw = math.radians(8)*(hx if head else bx)
            pitch = math.radians(4)*(hy if head else by)
            center_x, center_y = self.rig['head_c'] if head else self.rig['body_c']
            ax = math.cos(yaw)-1-math.sin(yaw)*.045
            ay = math.cos(pitch)-1
            ox = math.sin(yaw)*depth*self.w-ax*center_x*self.w
            oy = math.sin(pitch)*depth*self.h*.6-ay*center_y*self.h
            if name in ('hat','hair'):
                ox += clamp(fx-hx)*self.w*.015
                oy += clamp(fy-hy)*self.h*.0075
            result.append((ax,ox,ay,oy))
        return result

    def displacement(self, x, y, weights, pose, lean, squash, bend, bob=0, coefficients=None,
                     sway=None, leg_bend=None, breath=0.0):
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
        if sway:
            # 次级物理(life.py 的弹簧):身上松垮的部分晚一点才跟上来。
            # 帽尖绕帽基微旋转(越高处位移越大),发梢/裙摆下缘水平拖尾。
            hat_rot, hat_dx, hair_dx, hem_dx = sway[0], sway[1], sway[2], sway[3]
            rg = self.rig
            hair_top = sway[4] if len(sway) > 4 else rg['hair_top']*self.h
            w_hat, w_hair, w_skirt = weights[0], weights[2], weights[4]
            if w_hat:
                dx += w_hat*(hat_rot*(rg['hat_base_y']*self.h-y)*.55 + hat_dx)
                dy += w_hat*hat_rot*(x-rg['hat_pivot_x']*self.w)*.18
            if w_hair:
                span = max(1.0, hair_top - rg['hair_y0']*self.h)
                dx += w_hair*hair_dx*clamp((hair_top-y)/span,0.,1.)
            if w_skirt:
                dx += w_skirt*hem_dx*clamp((y-rg['skirt_y0']*self.h)
                                           /(rg['skirt_span']*self.h),0.,1.)
        if leg_bend:
            # 腿层膝弯剪切:膝线以下水平位移渐增(小腿绕膝的延迟弯折)
            ky, dxk = leg_bend
            dx += clamp((y-ky)/70.0, 0.0, 1.0)*dxk
        if breath:
            # 体积呼吸:胸/肩随吸气局部扩张(与全局 bob 相位错开),
            # 只作用在身体区权重上 —— 脸和帽不动,避免五官拉扯
            wb = weights[3] + weights[4] * 0.45
            bcx, bcy = self.rig['breath_c']
            dx += wb * breath * (x - bcx*self.w) * .020
            dy += wb * breath * (y - bcy*self.h) * .012
        return dx, dy

    def mesh(self, pose, lean=0., squash=1., bend=0., bob=0., sway=None,
             leg_bend=None, breath=0.0):
        pose = tuple(clamp(v) for v in pose)
        # sway 量化与 pet.py 的缓存键一致:旋转 1/150、位移 1/4 —— 台阶
        # 肉眼不可见,但静态时缓存几乎总是命中
        sway = ((round(sway[0]*100)/100,) + tuple(round(v*2)/2 for v in sway[1:])
                if sway else None)
        breath_q = round(breath * 8) / 8
        key = (pose, lean, squash, bend, bob, sway, leg_bend, breath_q)
        if key == self._mesh_key:
            return self._mesh
        coefficients = self._coefficients(pose)
        rows = [[self.displacement(x,y,self.weights[j][i],pose,lean,squash,bend,bob,
                                   coefficients,sway,leg_bend,breath_q)
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
        lcx, lcy = self.rig['light_c']
        dcx, dcy = self.rig['light_dc']
        shape = (lcx-x)*.07 + (lcy-y)*.025
        seam = -.018*math.exp(-((y-self.rig['seam_y'])/.045)**2)*weights['hair']
        limit = .08*(1-face)+.04*face
        return shape*material+seam, -(x-dcx)*.22*material, -(y-dcy)*.06*material, limit

    def light_gain(self, x, y, yaw, pitch):
        base,dx,dy,limit = self._gain_fields(x,y)
        return 1+clamp(base+yaw*dx+pitch*dy,-limit,limit)

    def lit_for(self, img, pose):
        """给任意分层图(帽/发)套用与底图一致的光照明暗场。

        明暗变化只由 pose 决定,与像素位置无关的部分复用同一张 24×24
        变化场;每层按 pose 键缓存,LRU 上限 6(与 lit_source 同策略)。"""
        key = (round(clamp(pose[0])*4), round(clamp(pose[1])*2))
        ck = (key, id(img))
        cached = self._layer_light_cache.get(ck)
        if cached is not None:
            self._layer_light_cache.move_to_end(ck)
            return cached
        changes = [clamp(base + key[0]/4*dx + key[1]/2*dy, -limit, limit)
                   for base, dx, dy, limit in self._light_fields]
        dark = Image.new("L", (24, 24))
        dark.putdata([round(max(0, -v)*255/.08) for v in changes])
        bright = Image.new("L", (24, 24))
        bright.putdata([round(max(0, v)*255/.08) for v in changes])
        dark = dark.resize(img.size, Image.Resampling.BILINEAR)
        bright = bright.resize(img.size, Image.Resampling.BILINEAR)
        alpha = img.getchannel("A")
        low = img.convert("RGB").point(
            [round(v*.92) for v in range(256)]*3).convert("RGBA")
        high = img.convert("RGB").point(
            [min(255, round(v*1.08)) for v in range(256)]*3).convert("RGBA")
        low.putalpha(alpha)
        high.putalpha(alpha)
        lit = Image.composite(low, img, dark)
        lit = Image.composite(high, lit, bright)
        self._layer_light_cache[ck] = lit
        while len(self._layer_light_cache) > 6:
            self._layer_light_cache.popitem(last=False)
        return lit

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
             *, pose=None, source=None, lighting=True, source_alpha_fixed=False,
             sway=None, source_offset=(0, 0), leg_bend=None, breath=0.0):
        pose = pose if pose is not None else (look_x,look_y)*3
        skip_clear = source is None or source_alpha_fixed
        source = source if source is not None else self.lit_source(pose) if lighting else self.img
        mesh = self.mesh(pose,lean_rad,squash,bend,bob,sway,leg_bend,breath)
        # 跳空格用的是底图的覆盖表,只对"和底图同尺寸、同原点"的源图成立。
        # 裁剪图层(腿/发)恰好落在底图被挖空的地方,按底图过滤会把整层滤光
        # —— 腿层上线后一直没画出来,就是这个原因。
        if skip_clear and source_offset == (0, 0) and source.size == self.img.size:
            mesh = [(box,q) for box,q in mesh if self._has_ink(q)]
        crop_back = None
        if source_offset != (0, 0):
            ox, oy = source_offset
            # Pillow 裁剪越过输出左/上边界的网格框时,按裁剪后的新原点重算
            # 映射,整格内容错位(实测腿层左上缺 15~19px)。把画布原点对齐到
            # 网格线,任何框都不会跨左/上边界;变形完再裁回原尺寸。
            sx = max([g for g in self.gxs if g <= ox] or [0])
            sy = max([g for g in self.gys if g <= oy] or [0])
            px, py = int(round(ox - sx)), int(round(oy - sy))
            if px or py:
                canvas = Image.new(source.mode, (source.width + px, source.height + py))
                canvas.paste(source, (px, py))
                crop_back = (px, py, px + source.width, py + source.height)
                source = canvas
            ox, oy = ox - px, oy - py
            # 输出框和采样四边形都要换到图层自己的坐标系
            mesh = [((bx0-ox, by0-oy, bx1-ox, by1-oy),
                     tuple(v-ox if i % 2 == 0 else v-oy for i, v in enumerate(q)))
                    for (bx0, by0, bx1, by1), q in mesh]
        # PIL 对 RGBA 做非最近邻变换时,每次都会先把整张源图转成预乘 RGBa、
        # 变完再转回 RGBA。源图绝大多数时候是 lit_source 缓存里那两张固定的
        # 光照图,把它们的预乘版缓存下来,每次变形就少一次整图转换(跳舞时
        # 变形缓存几乎不命中,每帧都走这里)。输出与 PIL 内部流程逐字节相同。
        if source.mode == 'RGBA':
            out = self._premultiplied(source).transform(
                source.size, Image.Transform.MESH, mesh, Image.Resampling.BILINEAR)
            out = out.convert('RGBA')
        else:
            out = source.transform(source.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        return out.crop(crop_back) if crop_back else out

    def _premultiplied(self, source):
        """源图的 RGBa 版本。只缓存 lit_source 缓存里的长寿图(按对象身份);
        每帧新画的五官贴图是临时 copy,缓存它只会白占内存,直接转换。"""
        hit = self._premul_cache.get(id(source))
        if hit is not None and hit[0] is source:
            self._premul_cache.move_to_end(id(source))
            return hit[1]
        premul = source.convert('RGBa')
        if any(img is source for img in self._light_cache.values()) or source is self.img:
            self._premul_cache[id(source)] = (source, premul)
            while len(self._premul_cache) > 3:
                self._premul_cache.popitem(last=False)
        return premul

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
