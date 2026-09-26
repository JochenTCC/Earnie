<?php
/**
 * Earnie LoxBerry plugin — minimal admin UI (Scope A).
 * Control via sudo $lbpbindir/earnie_ctl.sh (plugin bin/ + sudoers).
 */

require_once "loxberry_system.php";
require_once "loxberry_web.php";
require_once "loxberry_log.php";

$version = LBSystem::pluginversion();
$form = isset($_REQUEST['form']) ? $_REQUEST['form'] : 'main';
$L = LBSystem::readlanguage("language.ini");

$bins = LBSystem::get_binaries();
$sudo_bin = isset($bins['SUDO']) ? $bins['SUDO'] : 'sudo';
define('EARNIE_CTL', $sudo_bin . ' ' . rtrim($lbpbindir, '/') . '/earnie_ctl.sh');
define('EARNIE_SERVICE', 'earnie');
define('EARNIE_CONTAINER', 'earnie-productive');
define('EARNIE_DEFAULT_PORT', 8501);
define('EARNIE_PORT_MIN', 1024);
define('EARNIE_PORT_MAX', 65535);
define('EARNIE_GH_RELEASES', 'https://api.github.com/repos/JochenTCC/Earnie/releases?per_page=40');
define('EARNIE_SEMVER_RE', '/^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$/');

$earnie_plugin_env = rtrim($lbpconfigdir, '/') . '/plugin.env';
$earnie_compose_dir = rtrim($lbpdatadir, '/') . '/docker';

$log = LBLog::newLog([
	"name" => "Earnie",
	"filename" => "$lbplogdir/earnie.log",
	"append" => 1,
	"addtime" => 1,
]);
$log->LOGSTART("index.php called (form: $form)");

function earnie_ctl($action)
{
	$allowed = ["start", "stop", "restart", "pull"];
	if (!in_array($action, $allowed, true)) {
		return;
	}
	// pull can take minutes (image download) — keep async; start/stop/restart wait
	// so the POST redirect already reflects the new service/container status.
	$async = ($action === "pull");
	$cmd = EARNIE_CTL . " " . escapeshellarg($action);
	if ($async) {
		$cmd .= " > /dev/null 2>&1 &";
	}
	shell_exec($cmd);
}

function earnie_service_status()
{
	$out = shell_exec("systemctl show --value --property ActiveState " . EARNIE_SERVICE . " 2>/dev/null");
	return $out === null ? "unknown" : trim($out);
}

function earnie_container_status()
{
	$out = shell_exec("docker inspect -f '{{.State.Status}}' " . EARNIE_CONTAINER . " 2>/dev/null");
	return $out === null || trim($out) === "" ? "missing" : trim($out);
}

function earnie_image_label()
{
	$tags = shell_exec(
		"docker inspect -f '{{range .RepoTags}}{{.}} {{end}}' " . EARNIE_CONTAINER . " 2>/dev/null"
	);
	if ($tags !== null && trim($tags) !== "") {
		return trim($tags);
	}
	$id = shell_exec("docker inspect -f '{{.Image}}' " . EARNIE_CONTAINER . " 2>/dev/null");
	return $id === null || trim($id) === "" ? "—" : trim($id);
}

function earnie_running_version()
{
	$out = shell_exec(
		"docker exec " . EARNIE_CONTAINER
		. " python -c \"import version; print(version.__version__)\" 2>/dev/null"
	);
	if ($out === null) {
		return "";
	}
	$v = trim($out);
	return $v !== "" ? $v : "";
}

function earnie_parse_env_file($path)
{
	$vars = [];
	if (!is_readable($path)) {
		return $vars;
	}
	$lines = file($path, FILE_IGNORE_NEW_LINES);
	if ($lines === false) {
		return $vars;
	}
	foreach ($lines as $line) {
		$line = trim($line);
		if ($line === "" || $line[0] === "#") {
			continue;
		}
		$pos = strpos($line, "=");
		if ($pos === false) {
			continue;
		}
		$key = trim(substr($line, 0, $pos));
		$val = trim(substr($line, $pos + 1));
		if ($key !== "") {
			$vars[$key] = $val;
		}
	}
	return $vars;
}

function earnie_normalize_port($raw)
{
	if (!is_string($raw) && !is_int($raw)) {
		return null;
	}
	$s = trim((string) $raw);
	if ($s === "" || !ctype_digit($s)) {
		return null;
	}
	$port = (int) $s;
	if ($port < EARNIE_PORT_MIN || $port > EARNIE_PORT_MAX) {
		return null;
	}
	return $port;
}

function earnie_normalize_channel($raw)
{
	$s = is_string($raw) ? strtolower(trim($raw)) : "";
	if ($s === "prerelease" || $s === "pinned") {
		return $s;
	}
	return "stable";
}

function earnie_normalize_pinned($raw)
{
	$s = is_string($raw) ? trim($raw) : "";
	if ($s === "") {
		return "";
	}
	if ($s[0] === "v" || $s[0] === "V") {
		$s = substr($s, 1);
	}
	if (preg_match(EARNIE_SEMVER_RE, $s)) {
		return $s;
	}
	return null;
}

function earnie_normalize_auto_update($raw)
{
	if (is_bool($raw)) {
		return $raw ? "1" : "0";
	}
	$s = is_string($raw) || is_int($raw) ? strtolower(trim((string) $raw)) : "";
	if ($s === "1" || $s === "true" || $s === "yes" || $s === "on") {
		return "1";
	}
	return "0";
}

function earnie_read_settings($plugin_env)
{
	$vars = earnie_parse_env_file($plugin_env);
	$port = isset($vars["STREAMLIT_PORT"])
		? earnie_normalize_port($vars["STREAMLIT_PORT"])
		: null;
	$channel = isset($vars["EARNIE_CHANNEL"])
		? earnie_normalize_channel($vars["EARNIE_CHANNEL"])
		: "stable";
	$pinned = "";
	if (isset($vars["EARNIE_PINNED_VERSION"])) {
		$p = earnie_normalize_pinned($vars["EARNIE_PINNED_VERSION"]);
		$pinned = ($p !== null) ? $p : trim($vars["EARNIE_PINNED_VERSION"]);
	}
	$auto = isset($vars["EARNIE_AUTO_UPDATE"])
		? earnie_normalize_auto_update($vars["EARNIE_AUTO_UPDATE"])
		: "1";
	return [
		"port" => $port !== null ? $port : EARNIE_DEFAULT_PORT,
		"channel" => $channel,
		"pinned" => $pinned,
		"auto_update" => $auto,
	];
}

function earnie_channel_to_tag($channel, $pinned)
{
	if ($channel === "prerelease") {
		return "next";
	}
	if ($channel === "pinned") {
		$p = earnie_normalize_pinned($pinned);
		return ($p !== null && $p !== "") ? $p : "latest";
	}
	return "latest";
}

function earnie_write_plugin_env($path, $port, $channel, $pinned, $auto_update)
{
	$vars = earnie_parse_env_file($path);
	// Migrate away dead IMAGE (H13).
	unset($vars["IMAGE"]);
	$vars["EARNIE_CHANNEL"] = earnie_normalize_channel($channel);
	$vars["EARNIE_PINNED_VERSION"] = ($vars["EARNIE_CHANNEL"] === "pinned")
		? (string) $pinned
		: "";
	$vars["EARNIE_AUTO_UPDATE"] = ($vars["EARNIE_CHANNEL"] === "pinned")
		? "0"
		: earnie_normalize_auto_update($auto_update);
	$vars["STREAMLIT_PORT"] = (string) $port;

	$order = [
		"EARNIE_CHANNEL",
		"EARNIE_PINNED_VERSION",
		"EARNIE_AUTO_UPDATE",
		"STREAMLIT_PORT",
	];
	$lines = [
		"# Earnie LoxBerry plugin — local notes (do not commit secrets here)",
	];
	foreach ($order as $key) {
		$lines[] = $key . "=" . $vars[$key];
		unset($vars[$key]);
	}
	foreach ($vars as $key => $val) {
		$lines[] = $key . "=" . $val;
	}
	$dir = dirname($path);
	if (!is_dir($dir)) {
		mkdir($dir, 0755, true);
	}
	return file_put_contents($path, implode("\n", $lines) . "\n") !== false;
}

function earnie_host_tz()
{
	$path = "/etc/timezone";
	if (!is_readable($path)) {
		return "Europe/Vienna";
	}
	$tz = trim((string) file_get_contents($path));
	return $tz !== "" ? $tz : "Europe/Vienna";
}

function earnie_sync_compose_env($compose_dir, $port, $plugin_env = null, $tag = "latest")
{
	$script = rtrim($compose_dir, "/") . "/sync_compose_env.sh";
	if ($plugin_env !== null && is_file($script)) {
		$cmd = "bash " . escapeshellarg($script) . " "
			. escapeshellarg($plugin_env) . " "
			. escapeshellarg($compose_dir);
		shell_exec($cmd);
		$env_path = rtrim($compose_dir, "/") . "/.env";
		return is_readable($env_path);
	}
	if (!is_dir($compose_dir)) {
		mkdir($compose_dir, 0755, true);
	}
	$path = rtrim($compose_dir, "/") . "/.env";
	$body = "STREAMLIT_PORT=" . (int) $port
		. "\nEARNIE_IMAGE_TAG=" . $tag
		. "\nTZ=" . earnie_host_tz() . "\n";
	return file_put_contents($path, $body) !== false;
}

function earnie_host_url($port)
{
	$host = isset($_SERVER["HTTP_HOST"])
		? preg_replace("/:\\d+$/", "", $_SERVER["HTTP_HOST"])
		: "loxberry";
	return "http://" . $host . ":" . (int) $port;
}

function earnie_strip_v($tag)
{
	$t = trim((string) $tag);
	if ($t !== "" && ($t[0] === "v" || $t[0] === "V")) {
		$t = substr($t, 1);
	}
	return $t;
}

/**
 * @return array list of ['version' => string, 'prerelease' => bool]
 */
function earnie_fetch_releases()
{
	$ctx = stream_context_create([
		"http" => [
			"method" => "GET",
			"header" => "User-Agent: Earnie-LoxBerry-Plugin\r\n"
				. "Accept: application/vnd.github+json\r\n",
			"timeout" => 8,
			"ignore_errors" => true,
		],
	]);
	$raw = @file_get_contents(EARNIE_GH_RELEASES, false, $ctx);
	if ($raw === false || $raw === "") {
		return [];
	}
	$data = json_decode($raw, true);
	if (!is_array($data)) {
		return [];
	}
	$out = [];
	foreach ($data as $rel) {
		if (!is_array($rel) || empty($rel["tag_name"])) {
			continue;
		}
		$ver = earnie_strip_v($rel["tag_name"]);
		if (!preg_match(EARNIE_SEMVER_RE, $ver)) {
			continue;
		}
		$out[] = [
			"version" => $ver,
			"prerelease" => !empty($rel["prerelease"]),
		];
	}
	return $out;
}

function earnie_channel_latest($releases, $channel)
{
	foreach ($releases as $rel) {
		if ($channel === "stable" && !empty($rel["prerelease"])) {
			continue;
		}
		return $rel["version"];
	}
	return "";
}

$settings_error = "";
$settings_saved = false;
$pinned_invalid = false;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$action = isset($_POST["action"]) ? $_POST["action"] : "";
	if (in_array($action, ["start", "stop", "restart", "pull"], true)) {
		$log->INF("ctl action=$action");
		earnie_ctl($action);
		header("Location: index.php");
		exit;
	}
	if ($action === "save_settings") {
		$raw_port = isset($_POST["streamlit_port"]) ? $_POST["streamlit_port"] : "";
		$port = earnie_normalize_port($raw_port);
		$channel = earnie_normalize_channel(
			isset($_POST["earnie_channel"]) ? $_POST["earnie_channel"] : "stable"
		);
		$pinned_raw = isset($_POST["earnie_pinned"]) ? $_POST["earnie_pinned"] : "";
		$auto_raw = isset($_POST["earnie_auto_update"]) ? $_POST["earnie_auto_update"] : "0";
		$pinned = "";
		$ok = true;

		if ($port === null) {
			$settings_error = isset($L["MAIN.PORT_INVALID"])
				? $L["MAIN.PORT_INVALID"]
				: "Invalid port (use 1024–65535).";
			$log->ERR("invalid STREAMLIT_PORT=$raw_port");
			$ok = false;
		}
		if ($ok && $channel === "pinned") {
			$pinned_n = earnie_normalize_pinned($pinned_raw);
			if ($pinned_n === null || $pinned_n === "") {
				$settings_error = isset($L["MAIN.PINNED_INVALID"])
					? $L["MAIN.PINNED_INVALID"]
					: "Invalid pinned version (use SemVer, e.g. 2.5.3).";
				$log->ERR("invalid EARNIE_PINNED_VERSION=$pinned_raw");
				$ok = false;
				$pinned_invalid = true;
			} else {
				$pinned = $pinned_n;
			}
		}
		if ($ok) {
			$auto = ($channel === "pinned") ? "0" : earnie_normalize_auto_update($auto_raw);
			$ok_plugin = earnie_write_plugin_env(
				$earnie_plugin_env,
				$port,
				$channel,
				$pinned,
				$auto
			);
			$tag = earnie_channel_to_tag($channel, $pinned);
			$ok_compose = earnie_sync_compose_env(
				$earnie_compose_dir,
				$port,
				$earnie_plugin_env,
				$tag
			);
			if ($ok_plugin && $ok_compose) {
				$log->INF(
					"settings saved channel=$channel tag=$tag port=$port; pulling"
				);
				earnie_ctl("pull");
				header("Location: index.php?settings_saved=1");
				exit;
			}
			$settings_error = isset($L["MAIN.SETTINGS_SAVE_FAILED"])
				? $L["MAIN.SETTINGS_SAVE_FAILED"]
				: "Could not save settings.";
			$log->ERR("failed to write plugin.env or compose .env");
		}
	}
}

$settings = earnie_read_settings($earnie_plugin_env);
$streamlit_port = $settings["port"];
$earnie_channel = $settings["channel"];
$earnie_pinned = $settings["pinned"];
$earnie_auto_update = $settings["auto_update"];
$image_tag = earnie_channel_to_tag($earnie_channel, $earnie_pinned);

if (!is_dir($earnie_compose_dir) || !is_readable($earnie_compose_dir . "/.env")) {
	earnie_sync_compose_env(
		$earnie_compose_dir,
		$streamlit_port,
		$earnie_plugin_env,
		$image_tag
	);
}

$svc = earnie_service_status();
$ctr = earnie_container_status();
$image = earnie_image_label();
$running_ver = earnie_running_version();
$uiurl = earnie_host_url($streamlit_port);
$settings_saved = isset($_GET["settings_saved"]) && $_GET["settings_saved"] === "1";

$releases = earnie_fetch_releases();
$releases_ok = count($releases) > 0;
$channel_latest = earnie_channel_latest($releases, $earnie_channel);
$update_available = false;
if ($earnie_channel !== "pinned"
	&& $running_ver !== ""
	&& $channel_latest !== ""
	&& $running_ver !== $channel_latest
) {
	$update_available = true;
}

$channel_label = $earnie_channel;
if ($earnie_channel === "stable" && isset($L["MAIN.CHANNEL_STABLE"])) {
	$channel_label = $L["MAIN.CHANNEL_STABLE"];
} elseif ($earnie_channel === "prerelease" && isset($L["MAIN.CHANNEL_PRERELEASE"])) {
	$channel_label = $L["MAIN.CHANNEL_PRERELEASE"];
} elseif ($earnie_channel === "pinned" && isset($L["MAIN.CHANNEL_PINNED"])) {
	$channel_label = $L["MAIN.CHANNEL_PINNED"];
}

LBWeb::lbheader(
	$L["BASIC.LABEL_PLUGINTITLE"] . " V$version",
	"https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/loxberry-plugin.md",
	"",
	true
);
include "$lbptemplatedir/main.html";
LBWeb::lbfooter();
exit;
