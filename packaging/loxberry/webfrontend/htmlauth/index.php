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

$log = LBLog::newLog([
	"name" => "Earnie",
	"filename" => "$lbplogdir/earnie.log",
	"append" => 1,
	"addtime" => 1,
]);
$log->LOGSTART("index.php called (form: $form)");

// #region agent log
function earnie_dbg($hypothesisId, $location, $message, $data = [])
{
	$payload = [
		"sessionId" => "3c62b0",
		"runId" => "post-fix",
		"hypothesisId" => $hypothesisId,
		"location" => $location,
		"message" => $message,
		"data" => $data,
		"timestamp" => (int) round(microtime(true) * 1000),
	];
	$line = json_encode($payload, JSON_UNESCAPED_SLASHES) . "\n";
	@file_put_contents("/tmp/debug-3c62b0.log", $line, FILE_APPEND | LOCK_EX);
	if (!empty($GLOBALS['lbplogdir'])) {
		@file_put_contents($GLOBALS['lbplogdir'] . "/debug-3c62b0.log", $line, FILE_APPEND | LOCK_EX);
	}
}
// #endregion

function earnie_ctl($action)
{
	$allowed = ["start", "stop", "restart", "pull"];
	if (!in_array($action, $allowed, true)) {
		// #region agent log
		earnie_dbg("H1", "index.php:earnie_ctl", "action rejected", ["action" => $action]);
		// #endregion
		return;
	}
	$script = preg_replace('/^.*\s/', '', EARNIE_CTL);
	$cmd = EARNIE_CTL . " " . escapeshellarg($action) . " > /dev/null 2>&1 &";
	// #region agent log
	earnie_dbg("H2", "index.php:earnie_ctl", "shell_exec background", [
		"action" => $action,
		"cmd" => EARNIE_CTL . " " . escapeshellarg($action),
		"ctl_exists" => is_file($script),
		"svc_before" => earnie_service_status(),
		"ctr_before" => earnie_container_status(),
	]);
	// #endregion
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

function earnie_host_url()
{
	$host = isset($_SERVER['HTTP_HOST']) ? preg_replace('/:\\d+$/', '', $_SERVER['HTTP_HOST']) : "loxberry";
	return "http://" . $host . ":8501";
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
	$action = isset($_POST['action']) ? $_POST['action'] : '';
	// #region agent log
	earnie_dbg("H1", "index.php:POST", "post received", [
		"action" => $action,
		"post_keys" => array_keys($_POST),
		"action_allowed" => in_array($action, ["start", "stop", "restart", "pull"], true),
		"svc" => earnie_service_status(),
		"ctr" => earnie_container_status(),
		"earnie_ctl" => EARNIE_CTL,
	]);
	// #endregion
	if (in_array($action, ["start", "stop", "restart", "pull"], true)) {
		$log->INF("ctl action=$action");
		earnie_ctl($action);
	} else {
		// #region agent log
		earnie_dbg("H1", "index.php:POST", "post ignored empty/unknown action", ["action" => $action]);
		// #endregion
	}
	header("Location: index.php");
	exit;
}

$svc = earnie_service_status();
$ctr = earnie_container_status();
$image = earnie_image_label();
$uiurl = earnie_host_url();

LBWeb::lbheader(
	$L['BASIC.LABEL_PLUGINTITLE'] . " V$version",
	"https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/loxberry-plugin.md",
	"",
	true
);
include "$lbptemplatedir/main.html";
LBWeb::lbfooter();
exit;
