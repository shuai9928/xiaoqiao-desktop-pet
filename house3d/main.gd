extends Node3D

## 小乔 3D 小屋 · 试验窗口(I-25)
## 真 3D diorama 小屋:透明置顶无边框窗,鼠标视差+拖拽环绕+滚轮缩放,
## 秋千真 3D 枢轴摆动,小乔立绘剪纸立牌,水晶=AI状态灯,书桌=额度。
## 宪法:视觉中心是小乔;装饰不压人物;接触有锚定(坐垫承托+接触暗斑)。

const WIN_TITLE := "小乔3D小屋"
const CAM_TARGET := Vector3(0, 1.30, 0)
const SWING_TOP := Vector3(0, 2.16, 0.18)   # 秋千吊点(前梁下沿)
const ROPE_LEN := 1.34
const GIRL_H := 1.30                         # 立绘目标高度(米)

var hub: DataHub
var cam: Camera3D
var pivot: Node3D
var girl: Sprite3D
var crystal: MeshInstance3D
var crystal_mat: StandardMaterial3D
var gem_mat: StandardMaterial3D
var book_page_a: StandardMaterial3D
var book_page_b: StandardMaterial3D
var plaque: Label3D
var floor_shadow: MeshInstance3D
var menu: PopupMenu
var ui_font: FontFile

var phase := 0.0
var amp := 0.15
var push_timer := 6.0
var t_acc := 0.0

var cam_yaw := 0.0
var cam_pitch := 0.13
var cam_yaw_t := 0.0
var cam_pitch_t := 0.13
var cam_dist := 4.75
var cam_dist_t := 4.75
var mouse_ndc := Vector2.ZERO

var orbit_drag := false
var win_drag := false

var _applied_sig := ""
var _lock_path := ""
var w_scale := 1.0


func _ready() -> void:
	Engine.max_fps = 30
	_lock_path = ProjectSettings.globalize_path("res://instance.lock")
	_write_lock()
	var w := get_window()
	w.title = WIN_TITLE
	w.borderless = true
	w.always_on_top = true
	w.transparent = true
	w.unfocusable = true
	_place_window()
	w.mouse_passthrough_polygon = _silhouette()
	get_viewport().transparent_bg = true
	get_viewport().msaa_3d = Viewport.MSAA_4X
	_load_font()
	hub = DataHub.new()
	_build_scene()
	_build_menu()


# ---------------------------------------------------------------- 窗口

func _write_lock() -> void:
	var f := FileAccess.open(_lock_path, FileAccess.WRITE)
	if f:
		f.store_string(str(OS.get_process_id()))
		f.close()


func _exit_tree() -> void:
	if _lock_path != "" and FileAccess.file_exists(_lock_path):
		DirAccess.remove_absolute(_lock_path)


func _place_window() -> void:
	# HiDPI:按屏幕 DPI 缩放窗口(200% 屏 → 2 倍物理尺寸)
	var screen := DisplayServer.window_get_current_screen()
	var dpi := float(DisplayServer.screen_get_dpi(screen))
	w_scale = dpi / 96.0 if dpi > 96.0 and dpi <= 500.0 else 1.0
	var sz := Vector2i(int(560 * w_scale), int(500 * w_scale))
	get_window().size = sz
	var usable := DisplayServer.screen_get_usable_rect(screen)
	if OS.get_environment("HOUSE3D_CORNER") == "left":
		get_window().position = usable.position + Vector2i(
			int(24 * w_scale), usable.size.y - sz.y - int(10 * w_scale))
	else:
		get_window().position = usable.position + Vector2i(
			usable.size.x - sz.x - int(24 * w_scale), usable.size.y - sz.y - int(10 * w_scale))
	print("house3d: dpi=%d scale=%.2f size=%s usable=%s" % [int(dpi), w_scale, sz, usable])


func _silhouette() -> PackedVector2Array:
	# 屋形镂空:透明四角让鼠标穿透到桌面(不挡视野);随窗口缩放
	var sz := Vector2(get_window().size)
	var s := w_scale if w_scale > 0.0 else 1.0
	var inset := 16.0 * s
	return PackedVector2Array([
		Vector2(inset, sz.y - inset),
		Vector2(inset, 148.0 * s),
		Vector2(66.0 * s, 128.0 * s),
		Vector2(sz.x * 0.5, 30.0 * s),
		Vector2(sz.x - 66.0 * s, 128.0 * s),
		Vector2(sz.x - inset, 148.0 * s),
		Vector2(sz.x - inset, sz.y - inset),
	])


func _load_font() -> void:
	ui_font = FontFile.new()
	if ui_font.load_dynamic_font("C:/Windows/Fonts/msyh.ttc") != OK:
		ui_font = null


# ---------------------------------------------------------------- 场景搭建

func _mat(c: Color, rough := 0.88, emis := Color(0, 0, 0), e_energy := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = rough
	if e_energy > 0.0:
		m.emission_enabled = true
		m.emission = emis
		m.emission_energy_multiplier = e_energy
	return m


func _box(parent: Node3D, size: Vector3, pos: Vector3, mat: Material,
		rot_deg := Vector3.ZERO) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = size
	mi.mesh = mesh
	mi.material_override = mat
	mi.position = pos
	mi.rotation_degrees = rot_deg
	parent.add_child(mi)
	return mi


func _quad(parent: Node3D, size: Vector2, pos: Vector3, mat: Material,
		rot_deg := Vector3.ZERO) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var mesh := QuadMesh.new()
	mesh.size = size
	mi.mesh = mesh
	mi.material_override = mat
	mi.position = pos
	mi.rotation_degrees = rot_deg
	parent.add_child(mi)
	return mi


func _soft_shadow_mat(alpha := 0.38) -> StandardMaterial3D:
	# 径向渐变软影:边缘柔和,不生硬
	var grad := Gradient.new()
	grad.colors = PackedColorArray([Color(0, 0, 0, alpha), Color(0, 0, 0, 0.0)])
	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.fill = GradientTexture2D.FILL_RADIAL
	tex.fill_from = Vector2(0.5, 0.5)
	tex.fill_to = Vector2(0.5, 0.0)
	tex.width = 256
	tex.height = 256
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(1, 1, 1, 1)
	m.albedo_texture = tex
	return m


func _build_scene() -> void:
	# 环境:深紫夜空气氛,暖主光,禁 glow(宪法特效红线)
	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_CLEAR_COLOR
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.42, 0.38, 0.62)
	env.ambient_light_energy = 0.85
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.glow_enabled = false
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.light_color = Color(1.0, 0.93, 0.82)
	sun.light_energy = 1.05
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 9.0
	sun.rotation_degrees = Vector3(-42, 28, 0)
	add_child(sun)

	var fill := OmniLight3D.new()
	fill.light_color = Color(0.85, 0.72, 1.0)
	fill.light_energy = 0.55
	fill.omni_range = 5.0
	fill.position = Vector3(0, 2.3, 0.8)
	add_child(fill)

	cam = Camera3D.new()
	cam.fov = 38.0
	add_child(cam)
	cam.current = true

	_build_room()
	_build_swing()
	_build_ai_props()


func _build_room() -> void:
	var root := Node3D.new()
	root.name = "Room"
	add_child(root)

	var wall := _mat(Color(0.30, 0.25, 0.50))       # 深紫墙
	var wall2 := _mat(Color(0.25, 0.20, 0.44))
	var floor_m := _mat(Color(0.42, 0.31, 0.24), 0.7)   # 暖木地板
	var roof_m := _mat(Color(0.20, 0.17, 0.36))
	var gold := _mat(Color(0.79, 0.64, 0.27), 0.45)     # 金饰条
	var wood := _mat(Color(0.44, 0.33, 0.22), 0.75)

	# 地板(前缘 y=0 台口)
	_box(root, Vector3(3.4, 0.12, 2.4), Vector3(0, -0.06, -0.10), floor_m)
	# 地台前缘金线
	_box(root, Vector3(3.44, 0.02, 0.04), Vector3(0, 0.011, 1.10), gold)

	# 后墙(带月窗洞):洞 x -0.10..0.80, y 1.05..2.25
	_box(root, Vector3(3.4, 1.05, 0.08), Vector3(0, 0.525, -1.30), wall)
	_box(root, Vector3(3.4, 0.35, 0.08), Vector3(0, 2.425, -1.30), wall)
	_box(root, Vector3(1.60, 1.20, 0.08), Vector3(-0.90, 1.65, -1.30), wall)
	_box(root, Vector3(0.90, 1.20, 0.08), Vector3(1.25, 1.65, -1.30), wall)
	# 月窗金框
	_box(root, Vector3(0.98, 0.05, 0.10), Vector3(0.35, 2.27, -1.29), gold)
	_box(root, Vector3(0.98, 0.05, 0.10), Vector3(0.35, 1.03, -1.29), gold)
	_box(root, Vector3(0.05, 1.28, 0.10), Vector3(-0.12, 1.65, -1.29), gold)
	_box(root, Vector3(0.05, 1.28, 0.10), Vector3(0.82, 1.65, -1.29), gold)
	# 窗外夜空 + 月亮(微弱发光,只表达光源不糊结构)
	var sky_m := _mat(Color(0.16, 0.17, 0.34), 1.0, Color(0.13, 0.14, 0.30), 0.5)
	_quad(root, Vector2(1.30, 1.62), Vector3(0.35, 1.65, -1.42), sky_m)
	var moon_m := _mat(Color(0.95, 0.92, 0.78), 1.0, Color(0.9, 0.87, 0.7), 0.9)
	var moon := MeshInstance3D.new()
	var mm := SphereMesh.new()
	mm.radius = 0.085
	mm.height = 0.17
	moon.mesh = mm
	moon.material_override = moon_m
	moon.position = Vector3(0.62, 1.95, -1.38)
	root.add_child(moon)
	var star_m := _mat(Color(0.9, 0.9, 1.0), 1.0, Color(0.8, 0.8, 1.0), 0.8)
	for p in [Vector3(0.12, 2.05, -1.40), Vector3(0.28, 1.32, -1.40), Vector3(0.05, 1.62, -1.40)]:
		_quad(root, Vector2(0.035, 0.035), p, star_m)

	# 左墙(厚 0.1,纵深化)
	_box(root, Vector3(0.10, 2.6, 2.4), Vector3(-1.70, 1.30, -0.10), wall2)
	# 右墙(矮一半,保持开口感)
	_box(root, Vector3(0.10, 1.6, 2.4), Vector3(1.70, 0.80, -0.10), wall2)

	# 坡屋顶 + 屋脊金条
	_box(root, Vector3(3.95, 0.07, 2.75), Vector3(-0.97, 3.05, -0.10), roof_m, Vector3(0, 0, 26))
	_box(root, Vector3(3.95, 0.07, 2.75), Vector3(0.97, 3.05, -0.10), roof_m, Vector3(0, 0, -26))
	_box(root, Vector3(3.6, 0.06, 0.12), Vector3(0, 3.36, -0.10), gold)

	# 秋千架:前梁+双立柱(绳挂前梁下沿,对齐 I-24 结论)
	_box(root, Vector3(3.1, 0.10, 0.12), SWING_TOP + Vector3(0, 0.05, 0), wood)
	_box(root, Vector3(0.09, 2.21, 0.10), Vector3(-1.50, 1.105, SWING_TOP.z), wood)
	_box(root, Vector3(0.09, 2.21, 0.10), Vector3(1.50, 1.105, SWING_TOP.z), wood)


func _build_swing() -> void:
	var root := Node3D.new()
	root.name = "Swing"
	add_child(root)

	pivot = Node3D.new()
	pivot.position = SWING_TOP - Vector3(0, 0.05, 0)
	root.add_child(pivot)

	var rope_m := _mat(Color(0.79, 0.66, 0.42), 0.6)
	var cushion_m := _mat(Color(0.48, 0.37, 0.65), 0.85)
	var seat_m := _mat(Color(0.30, 0.22, 0.15), 0.75)

	var seat_y := SWING_TOP.y - 0.05 - ROPE_LEN
	for rx in [-0.22, 0.22]:
		var rope := MeshInstance3D.new()
		var cyl := CylinderMesh.new()
		cyl.top_radius = 0.012
		cyl.bottom_radius = 0.012
		cyl.height = ROPE_LEN
		rope.mesh = cyl
		rope.material_override = rope_m
		rope.position = Vector3(rx, -ROPE_LEN * 0.5, 0)
		pivot.add_child(rope)
	# 座板 + 坐垫(重量:垫在板上,人压垫)
	_box(pivot, Vector3(0.58, 0.045, 0.30), Vector3(0, -ROPE_LEN + 0.02, 0), seat_m)
	_box(pivot, Vector3(0.62, 0.055, 0.34), Vector3(0, -ROPE_LEN + 0.065, 0), cushion_m)
	# 坐垫上的接触暗斑(锚定表达,径向软边)
	_quad(pivot, Vector2(0.36, 0.22), Vector3(0, -ROPE_LEN + 0.096, 0.01),
		_soft_shadow_mat(0.42), Vector3(-90, 0, 0))

	# 小乔立绘(剪纸立牌,unshaded 保原画色彩;素材运行时加载,不复制)
	girl = Sprite3D.new()
	girl.shaded = false
	girl.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	# 不透明预通道:兼容渲染器+透明窗口下保证与墙体深度排序正确
	girl.alpha_cut = SpriteBase3D.ALPHA_CUT_OPAQUE_PREPASS
	var img := Image.load_from_file(
		ProjectSettings.globalize_path("res://").path_join("../assets/scene/girl.png"))
	if img != null:
		girl.texture = ImageTexture.create_from_image(img)
		girl.pixel_size = GIRL_H / float(img.get_height())
	else:
		push_warning("girl.png 加载失败,使用占位块")
		var ph := Image.create(64, 64, false, Image.FORMAT_RGBA8)
		ph.fill(Color(1, 0, 1, 1))
		girl.texture = ImageTexture.create_from_image(ph)
		girl.pixel_size = GIRL_H / 64.0
	# pivot 局部坐标:座位在 -ROPE_LEN,人物臀部落在坐垫上
	girl.position = Vector3(0, -ROPE_LEN + GIRL_H * 0.5 - 0.02, 0.02)
	pivot.add_child(girl)
	print("house3d: girl tex=%s pos=%s vis_in_tree=%s" % [
		girl.texture != null, girl.global_position, girl.is_visible_in_tree()])

	# 地面软影(径向渐变,随摆动伸缩)
	floor_shadow = _quad(root, Vector2(1.6, 0.8), Vector3(0, 0.012, 0.15),
		_soft_shadow_mat(0.4), Vector3(-90, 0, 0))


func _build_ai_props() -> void:
	var root := Node3D.new()
	root.name = "AIProps"
	add_child(root)

	var wood := _mat(Color(0.30, 0.22, 0.15), 0.75)
	var gold := _mat(Color(0.79, 0.64, 0.27), 0.45)

	# 右侧书桌:魔法书=额度入口
	_box(root, Vector3(0.12, 0.44, 0.12), Vector3(1.18, 0.22, -0.40), wood)
	_box(root, Vector3(0.58, 0.04, 0.48), Vector3(1.18, 0.46, -0.40), wood)
	# 摊开的书:封面 + 两页(页色=额度状态)
	var cover := _box(root, Vector3(0.38, 0.016, 0.28), Vector3(1.18, 0.49, -0.40),
		_mat(Color(0.42, 0.30, 0.62), 0.8))
	cover.set_meta("hint", "book")
	book_page_a = _mat(Color(0.92, 0.87, 0.76), 0.9, Color(0.35, 0.90, 0.55), 0.25)
	book_page_b = _mat(Color(0.90, 0.85, 0.74), 0.9, Color(0.35, 0.90, 0.55), 0.25)
	_box(root, Vector3(0.16, 0.022, 0.24), Vector3(1.085, 0.505, -0.40), book_page_a,
		Vector3(0, 0, 8))
	_box(root, Vector3(0.16, 0.022, 0.24), Vector3(1.275, 0.505, -0.40), book_page_b,
		Vector3(0, 0, -8))
	# 额度宝石(色随剩余额度)
	gem_mat = _mat(Color(0.2, 0.2, 0.3), 0.4, Color(0.35, 0.9, 0.55), 1.1)
	var gem := MeshInstance3D.new()
	var sm := SphereMesh.new()
	sm.radius = 0.035
	sm.height = 0.07
	gem.mesh = sm
	gem.material_override = gem_mat
	gem.position = Vector3(1.40, 0.545, -0.30)
	root.add_child(gem)

	# 水晶挂灯:AI 聚合状态(挂前梁下沿,z 与梁一致,不悬空)
	var thread := MeshInstance3D.new()
	var tc := CylinderMesh.new()
	tc.top_radius = 0.004
	tc.bottom_radius = 0.004
	tc.height = 0.22
	thread.mesh = tc
	thread.material_override = gold
	thread.position = Vector3(0.72, 2.02, SWING_TOP.z)
	root.add_child(thread)
	crystal = MeshInstance3D.new()
	var cm := SphereMesh.new()
	cm.radius = 0.075
	cm.height = 0.15
	crystal.mesh = cm
	crystal_mat = _mat(Color(0.25, 0.18, 0.42), 0.35,
		DataHub.LIGHT_COLORS["idle"], 0.8)
	crystal.material_override = crystal_mat
	crystal.position = Vector3(0.72, 1.86, SWING_TOP.z)
	root.add_child(crystal)

	# 墙牌(挂在左墙,避让人物;真实数据,缺数据如实写未接入)
	plaque = Label3D.new()
	if ui_font != null:
		plaque.font = ui_font
	plaque.font_size = 30
	plaque.pixel_size = 0.0034
	plaque.outline_size = 10
	plaque.outline_modulate = Color(0.08, 0.06, 0.14, 0.9)
	plaque.modulate = Color(0.96, 0.93, 0.88)
	plaque.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	plaque.text = "AI 状态 · 读取中…"
	plaque.position = Vector3(-1.02, 1.94, -1.18)
	root.add_child(plaque)


# ---------------------------------------------------------------- 菜单

func _build_menu() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	menu = PopupMenu.new()
	menu.add_check_item("鼠标穿透(整窗)", 1)
	menu.add_check_item("窗口置顶", 2)
	menu.add_separator()
	menu.add_item("退出", 9)
	menu.set_item_checked(1, true)
	menu.id_pressed.connect(_on_menu)
	layer.add_child(menu)


func _on_menu(id: int) -> void:
	match id:
		1:
			var w := get_window()
			var on := not w.mouse_passthrough
			w.mouse_passthrough = on
			menu.set_item_checked(0, on)
		2:
			var w := get_window()
			var on := not w.always_on_top
			w.always_on_top = on
			menu.set_item_checked(1, on)
		9:
			get_tree().quit()


# ---------------------------------------------------------------- 输入

func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton:
		var mb := e as InputEventMouseButton
		if mb.pressed:
			if mb.button_index == MOUSE_BUTTON_RIGHT:
				_open_menu()
			elif mb.button_index == MOUSE_BUTTON_MIDDLE:
				win_drag = true
			elif mb.button_index == MOUSE_BUTTON_LEFT:
				if mb.ctrl_pressed:
					win_drag = true
				else:
					orbit_drag = true
		else:
			if mb.button_index in [MOUSE_BUTTON_MIDDLE, MOUSE_BUTTON_LEFT]:
				win_drag = false
				orbit_drag = false
		if mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			cam_dist_t = clampf(cam_dist_t - 0.28, 3.6, 5.8)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			cam_dist_t = clampf(cam_dist_t + 0.28, 3.6, 5.8)
	elif e is InputEventMouseMotion:
		var mm := e as InputEventMouseMotion
		var vp := get_viewport().get_visible_rect().size
		mouse_ndc = (mm.position / vp) * 2.0 - Vector2.ONE
		if win_drag:
			get_window().position += Vector2i(mm.relative)
		elif orbit_drag:
			cam_yaw_t = clampf(cam_yaw_t - mm.relative.x * 0.004, -0.55, 0.55)
			cam_pitch_t = clampf(cam_pitch_t + mm.relative.y * 0.003, -0.06, 0.30)


func _open_menu() -> void:
	var mp := get_viewport().get_mouse_position()
	menu.popup(Rect2i(get_window().position + Vector2i(mp), Vector2i(160, 0)))


# ---------------------------------------------------------------- 主循环

func _process(dt: float) -> void:
	t_acc += dt
	hub.poll(t_acc)
	_apply_data_if_changed()

	# 秋千相位:渐稳 + 周期性轻推(潜意识存在感,不做夸张运动)
	phase += dt * 2.1
	push_timer -= dt
	if push_timer <= 0.0:
		push_timer = randf_range(5.0, 9.0)
		amp = minf(amp + 0.05, 0.16)
	amp = maxf(amp - dt * 0.006, 0.075)
	pivot.rotation.z = amp * sin(phase)
	if girl != null:
		girl.scale = Vector3(1.0, 1.0 + 0.006 * sin(t_acc * 1.6), 1.0)
	# 地面软影随摆动
	if floor_shadow != null:
		var th := pivot.rotation.z
		floor_shadow.scale = Vector3(1.0 + 0.5 * absf(th), 1.0, 1.0)
		floor_shadow.rotation.y = th * 0.5

	# 相机:鼠标视差 + 拖拽环绕 + 滚轮(平滑趋近)
	cam_yaw = lerpf(cam_yaw, cam_yaw_t, minf(1.0, dt * 6.0))
	cam_pitch = lerpf(cam_pitch, cam_pitch_t, minf(1.0, dt * 6.0))
	cam_dist = lerpf(cam_dist, cam_dist_t, minf(1.0, dt * 6.0))
	var dir := Vector3(sin(cam_yaw), 0, cos(cam_yaw))
	var off := dir * cos(cam_pitch) + Vector3(0, sin(cam_pitch), 0)
	var par := Vector3(mouse_ndc.x * 0.20, -mouse_ndc.y * 0.10, 0)
	cam.position = CAM_TARGET + off * cam_dist + par
	cam.look_at(CAM_TARGET)

	# 水晶灯动效(语义同 ai_light_style)
	var col: Color = DataHub.LIGHT_COLORS[hub.agg]
	var energy := 0.8
	match hub.agg:
		"running":
			energy = 0.55 + 0.45 * (0.5 + 0.5 * sin(t_acc * TAU / 2.4))
		"waiting":
			energy = 1.0 if fmod(t_acc, 1.2) < 0.6 else 0.2
		"error":
			energy = 1.0 if fmod(t_acc, 0.5) < 0.25 else 0.15
		_:
			energy = 0.45
	crystal_mat.emission = col
	crystal_mat.emission_energy_multiplier = energy
	crystal.rotate_y(dt * 0.8)
	crystal.position.y = 1.86 + 0.012 * sin(t_acc * 1.3)
	gem_mat.emission_energy_multiplier = 0.9 + 0.25 * sin(t_acc * 1.1)


func _apply_data_if_changed() -> void:
	var fh: Variant = hub.quota.get("fh", -1.0)
	var sd: Variant = hub.quota.get("sd", -1.0)
	var sig := "%s|%s|%s|%d" % [hub.agg, fh, sd, hub.codex_cycles.size()]
	if sig == _applied_sig:
		return
	_applied_sig = sig
	# 铭牌:三行 = 会话聚合 / Claude 两周期(缺数据如实)
	var agg_label: String = {"running": "运行中", "waiting": "等你", "error": "出错", "idle": "空闲"}[hub.agg]
	var line1 := "AI %s · 会话 %d" % [agg_label, hub.sessions.size()]
	var line2 := ""
	var line3 := ""
	if typeof(fh) in [TYPE_FLOAT, TYPE_INT] and fh >= 0:
		line2 = "Claude 5小时剩%s%%" % _fmt_pct(100.0 - float(fh))
		line3 = "本周剩%s%%" % _fmt_pct(100.0 - float(sd))
	else:
		line2 = "Claude 额度 未接入"
	if hub.codex_cycles.size() > 0:
		line3 = (line3 + " · " if line3 != "" else "") + "Codex已接入"
	plaque.text = line1 + "\n" + line2 + (("\n" + line3) if line3 != "" else "")
	# 书页色=额度状态
	var qc := hub.quota_color()
	for m in [book_page_a, book_page_b]:
		m.emission = qc
		m.emission_energy_multiplier = 0.28
	gem_mat.emission = qc


func _fmt_pct(v: float) -> String:
	return str(int(round(clampf(v, 0.0, 100.0))))
