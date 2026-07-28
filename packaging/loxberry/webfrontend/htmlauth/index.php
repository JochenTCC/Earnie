<?php
/**
 * Earnie LoxBerry plugin — minimal admin UI (Scope A).
 * Control via sudo REPLACELBPSBINDIR/earnie_ctl.sh (LoxBerry sbin sudoers).
 */

require_once "loxberry_system.php";
require_once "loxberry_web.php";
require_once "loxberry_log.php";

$version = LBSystem::pluginversion();
$form = isset($_REQUEST['form']) ? $_REQUEST['form'] : 'main';
$L = LBSystem::readlanguage("language.ini");

define('EARNIE_CTL', 'sudo REPLACELBPSBINDIR/earnie_ctl.sh');
define('EARNIE_SERVICE', 'earnie');
define('EARNIE_CONTAINER', 'earnie-productive');

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
	shell_exec(EARNIE_CTL . " " . escapeshellarg($action) . " > /dev/null 2>&1 &");
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
	if (in_array($action, ["start", "stop", "restart", "pull"], true)) {
		$log->INF("ctl action=$action");
		earnie_ctl($action);
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
