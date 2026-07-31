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

function earnie_read_streamlit_port($plugin_env)
{
	$vars = earnie_parse_env_file($plugin_env);
	$port = isset($vars["STREAMLIT_PORT"])
		? earnie_normalize_port($vars["STREAMLIT_PORT"])
		: null;
	return $port !== null ? $port : EARNIE_DEFAULT_PORT;
}

function earnie_write_plugin_env($path, $port)
{
	$vars = earnie_parse_env_file($path);
	if (!isset($vars["IMAGE"])) {
		$vars["IMAGE"] = "ghcr.io/jochentcc/earnie-energy:latest";
	}
	$vars["STREAMLIT_PORT"] = (string) $port;
	$lines = [
		"# Earnie LoxBerry plugin — local notes (do not commit secrets here)",
		"IMAGE=" . $vars["IMAGE"],
		"STREAMLIT_PORT=" . $vars["STREAMLIT_PORT"],
	];
	foreach ($vars as $key => $val) {
		if ($key === "IMAGE" || $key === "STREAMLIT_PORT") {
			continue;
		}
		$lines[] = $key . "=" . $val;
	}
	$dir = dirname($path);
	if (!is_dir($dir)) {
		mkdir($dir, 0755, true);
	}
	return file_put_contents($path, implode("\n", $lines) . "\n") !== false;
}

function earnie_sync_compose_env($compose_dir, $port)
{
	if (!is_dir($compose_dir)) {
		mkdir($compose_dir, 0755, true);
	}
	$path = rtrim($compose_dir, "/") . "/.env";
	return file_put_contents($path, "STREAMLIT_PORT=" . (int) $port . "\n") !== false;
}

function earnie_host_url($port)
{
	$host = isset($_SERVER["HTTP_HOST"])
		? preg_replace("/:\\d+$/", "", $_SERVER["HTTP_HOST"])
		: "loxberry";
	return "http://" . $host . ":" . (int) $port;
}

$port_error = "";
$port_saved = false;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$action = isset($_POST["action"]) ? $_POST["action"] : "";
	if (in_array($action, ["start", "stop", "restart", "pull"], true)) {
		$log->INF("ctl action=$action");
		earnie_ctl($action);
		header("Location: index.php");
		exit;
	}
	if ($action === "save_port") {
		$raw = isset($_POST["streamlit_port"]) ? $_POST["streamlit_port"] : "";
		$port = earnie_normalize_port($raw);
		if ($port === null) {
			$port_error = isset($L["MAIN.PORT_INVALID"])
				? $L["MAIN.PORT_INVALID"]
				: "Invalid port (use 1024–65535).";
			$log->ERR("invalid STREAMLIT_PORT=$raw");
		} else {
			$ok_plugin = earnie_write_plugin_env($earnie_plugin_env, $port);
			$ok_compose = earnie_sync_compose_env($earnie_compose_dir, $port);
			if ($ok_plugin && $ok_compose) {
				$log->INF("STREAMLIT_PORT=$port saved; restarting");
				earnie_ctl("restart");
				header("Location: index.php?port_saved=1");
				exit;
			}
			$port_error = isset($L["MAIN.PORT_SAVE_FAILED"])
				? $L["MAIN.PORT_SAVE_FAILED"]
				: "Could not save port settings.";
			$log->ERR("failed to write plugin.env or compose .env");
		}
	}
}

$streamlit_port = earnie_read_streamlit_port($earnie_plugin_env);
if (!is_dir($earnie_compose_dir) || !is_readable($earnie_compose_dir . "/.env")) {
	earnie_sync_compose_env($earnie_compose_dir, $streamlit_port);
}
$svc = earnie_service_status();
$ctr = earnie_container_status();
$image = earnie_image_label();
$uiurl = earnie_host_url($streamlit_port);
$port_saved = isset($_GET["port_saved"]) && $_GET["port_saved"] === "1";

LBWeb::lbheader(
	$L["BASIC.LABEL_PLUGINTITLE"] . " V$version",
	"https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/loxberry-plugin.md",
	"",
	true
);
include "$lbptemplatedir/main.html";
LBWeb::lbfooter();
exit;
