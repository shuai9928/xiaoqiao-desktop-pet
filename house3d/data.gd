class_name DataHub
extends RefCounted

## 3D 小屋数据源(I-25):复用桌宠现有磁盘数据通道,零新采集。
## 会话灯:ai_sessions/*.json(结构同 pet.py scan_ai_sessions);
## 额度:Claude plan-usage-history.json(parse_quota 同构)+ ai_quota_codex.json。
## 缺数据如实标注"未接入",不编造。节流对齐 pet.py:会话 2s、额度 60s。

const LIGHT_COLORS := {
	"running": Color(0.62, 0.40, 1.00),
	"waiting": Color(1.00, 0.62, 0.25),
	"error": Color(1.00, 0.28, 0.30),
	"done": Color(0.35, 0.90, 0.55),
	"idle": Color(0.55, 0.52, 0.68),
}

# 会话过期阈值(与 pet.py ai_light_style 一致)
const STALE_LIMIT := {"running": 2400.0, "waiting": 7200.0, "error": 3600.0}

var sessions: Array = []
var agg := "idle"            # error > waiting > running > idle(水晶灯)
var quota := {}              # {fh, sd} = Claude 已用百分比,缺则 {}
var codex_cycles: Array = []
var pet_root := ""

var _t_sessions := -1e9
var _t_quota := -1e9


func _init() -> void:
	pet_root = ProjectSettings.globalize_path("res://").path_join("..")


func poll(now_s: float) -> void:
	if now_s - _t_sessions >= 2.0:
		_t_sessions = now_s
		_scan_sessions(now_s)
	if now_s - _t_quota >= 60.0:
		_t_quota = now_s
		_read_quota()


func _scan_sessions(now_s: float) -> void:
	sessions = []
	var dir := DirAccess.open(pet_root.path_join("ai_sessions"))
	if dir != null:
		for f in dir.get_files():
			if not f.ends_with(".json"):
				continue
			var txt := FileAccess.get_file_as_string(pet_root.path_join("ai_sessions").path_join(f))
			if txt.is_empty():
				continue
			var j: Variant = JSON.parse_string(txt)
			if typeof(j) == TYPE_DICTIONARY:
				sessions.append(j)
	agg = _aggregate(now_s)


func _session_stale(s: Dictionary, now_s: float) -> bool:
	if s.get("stale", false):
		return true
	var up := float(s.get("updated", 0.0))
	if up <= 0.0:
		return true
	var st: String = s.get("state", "idle")
	if STALE_LIMIT.has(st) and now_s - up > STALE_LIMIT[st]:
		return true
	return false


func _aggregate(now_s: float) -> String:
	# 同 pet.py crystal_state:error > waiting > running,其余(含 done)归 idle
	var has := {}
	for s in sessions:
		if typeof(s) != TYPE_DICTIONARY:
			continue
		var st: String = s.get("state", "idle")
		if st.is_empty():
			continue
		if not _session_stale(s, now_s):
			has[st] = true
	for st in ["error", "waiting", "running"]:
		if has.has(st):
			return st
	return "idle"


func _read_quota() -> void:
	quota = {}
	var base := OS.get_environment("LOCALAPPDATA")
	if not base.is_empty():
		var pkg_dir := DirAccess.open(base.path_join("Packages"))
		if pkg_dir != null:
			for p in pkg_dir.get_directories():
				if not p.begins_with("Claude_"):
					continue
				var fp := base.path_join("Packages").path_join(p).path_join(
					"LocalCache/Roaming/Claude/plan-usage-history.json")
				if FileAccess.file_exists(fp):
					var j: Variant = JSON.parse_string(FileAccess.get_file_as_string(fp))
					if typeof(j) == TYPE_DICTIONARY and j.has("samples"):
						quota = _parse_quota(j["samples"])
					break
	codex_cycles = []
	var cp := pet_root.path_join("ai_quota_codex.json")
	if FileAccess.file_exists(cp):
		var cj: Variant = JSON.parse_string(FileAccess.get_file_as_string(cp))
		if typeof(cj) == TYPE_DICTIONARY and typeof(cj.get("cycles")) == TYPE_ARRAY:
			codex_cycles = cj["cycles"]


func _parse_quota(samples: Variant) -> Dictionary:
	# 同 pet.py parse_quota:取最近一条含 fh/sd 的样本(reset_est 本批不做)
	var valid: Array = []
	var arr: Array = samples if typeof(samples) == TYPE_ARRAY else []
	for i in range(arr.size() - 1, -1, -1):
		var s: Variant = arr[i]
		if typeof(s) != TYPE_DICTIONARY:
			continue
		var u: Variant = s.get("u")
		if typeof(u) != TYPE_DICTIONARY:
			continue
		if typeof(u.get("fh")) in [TYPE_FLOAT, TYPE_INT] \
				or typeof(u.get("sd")) in [TYPE_FLOAT, TYPE_INT]:
			valid.append(s)
	if valid.is_empty():
		return {}
	var latest: Dictionary = valid[0]
	var u2: Dictionary = latest.get("u", {})
	return {"fh": u2.get("fh", -1.0), "sd": u2.get("sd", -1.0), "t": latest.get("t", 0.0)}


func quota_worst_remaining() -> float:
	# 剩余百分比最小值(两周期取紧的);无数据返回 -1
	if quota.is_empty():
		return -1.0
	var vals: Array = []
	for k in ["fh", "sd"]:
		var v: Variant = quota.get(k, -1.0)
		if typeof(v) in [TYPE_FLOAT, TYPE_INT] and v >= 0:
			vals.append(100.0 - float(v))
	if vals.is_empty():
		return -1.0
	vals.sort()
	return vals[0]


func quota_color() -> Color:
	var r := quota_worst_remaining()
	if r < 0.0:
		return LIGHT_COLORS["idle"]
	if r > 40.0:
		return LIGHT_COLORS["done"]
	if r > 15.0:
		return LIGHT_COLORS["waiting"]
	return LIGHT_COLORS["error"]
