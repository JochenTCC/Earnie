<?php
/**
 * Version of the image a channel actually pulls (ghcr.io/jochentcc/earnie-energy:<tag>).
 *
 * Read from the OCI label org.opencontainers.image.version (set by scripts/build_container.py)
 * via the anonymous registry API. GitHub Releases are not used here: a release can be
 * published without moving :next / :latest (release workflow targets=ha).
 * No LoxBerry dependencies, so it can be run with plain php-cli.
 */

define('EARNIE_GHCR_REPO', 'jochentcc/earnie-energy');
define('EARNIE_GHCR_VERSION_LABEL', 'org.opencontainers.image.version');
define('EARNIE_GHCR_UA', 'User-Agent: Earnie-LoxBerry-Plugin');
define('EARNIE_GHCR_MANIFEST_ACCEPT', 'Accept: '
	. 'application/vnd.oci.image.index.v1+json,'
	. 'application/vnd.docker.distribution.manifest.list.v2+json,'
	. 'application/vnd.oci.image.manifest.v1+json,'
	. 'application/vnd.docker.distribution.manifest.v2+json');

/**
 * GET without following redirects.
 *
 * @return array|null ['status' => int, 'location' => string, 'body' => string]; null on transport error
 */
function earnie_ghcr_get($url, $headers)
{
	$ctx = stream_context_create([
		"http" => [
			"method" => "GET",
			"header" => implode("\r\n", $headers) . "\r\n",
			"timeout" => 8,
			"ignore_errors" => true,
			"follow_location" => 0,
		],
	]);
	$body = @file_get_contents($url, false, $ctx);
	$raw = function_exists('http_get_last_response_headers')
		? http_get_last_response_headers()
		: (isset($http_response_header) ? $http_response_header : null);
	if ($body === false || !is_array($raw) || count($raw) === 0) {
		return null;
	}
	$status = 0;
	if (preg_match('#^HTTP/\S+\s+(\d{3})#', $raw[0], $m)) {
		$status = (int) $m[1];
	}
	$location = "";
	foreach ($raw as $line) {
		if (stripos($line, "Location:") === 0) {
			$location = trim(substr($line, 9));
		}
	}
	return ["status" => $status, "location" => $location, "body" => $body];
}

/**
 * @return array|string decoded JSON object, or an error string
 */
function earnie_ghcr_get_json($url, $headers, $what)
{
	$res = earnie_ghcr_get($url, $headers);
	if ($res === null) {
		return "$what: network error";
	}
	if ($res["status"] !== 200) {
		return "$what: HTTP " . $res["status"];
	}
	$data = json_decode($res["body"], true);
	return is_array($data) ? $data : "$what: invalid JSON";
}

/**
 * @return array ['version' => string, 'error' => string] — exactly one of them is non-empty
 */
function earnie_ghcr_tag_version($tag)
{
	$fail = function ($msg) {
		return ["version" => "", "error" => $msg];
	};
	$repo = EARNIE_GHCR_REPO;
	$tok = earnie_ghcr_get_json(
		"https://ghcr.io/token?scope=repository:$repo:pull",
		[EARNIE_GHCR_UA],
		"token"
	);
	if (is_string($tok)) {
		return $fail($tok);
	}
	if (empty($tok["token"]) || !is_string($tok["token"])) {
		return $fail("token: missing in response");
	}
	$auth = "Authorization: Bearer " . $tok["token"];
	$base = "https://ghcr.io/v2/$repo";
	$headers = [EARNIE_GHCR_UA, $auth, EARNIE_GHCR_MANIFEST_ACCEPT];

	$man = earnie_ghcr_get_json("$base/manifests/" . rawurlencode($tag), $headers, "manifest :$tag");
	if (is_string($man)) {
		return $fail($man);
	}
	if (isset($man["manifests"]) && is_array($man["manifests"])) {
		// Multi-arch index: every platform carries the same labels — take the first real one
		// (buildx attestation entries have platform os "unknown").
		$digest = "";
		foreach ($man["manifests"] as $entry) {
			$os = isset($entry["platform"]["os"]) ? $entry["platform"]["os"] : "";
			if ($os !== "" && $os !== "unknown" && !empty($entry["digest"])) {
				$digest = $entry["digest"];
				break;
			}
		}
		if ($digest === "") {
			return $fail("manifest :$tag: no platform image in index");
		}
		$man = earnie_ghcr_get_json("$base/manifests/$digest", $headers, "platform manifest");
		if (is_string($man)) {
			return $fail($man);
		}
	}
	if (empty($man["config"]["digest"])) {
		return $fail("manifest :$tag: no config digest");
	}

	$blob = earnie_ghcr_get("$base/blobs/" . $man["config"]["digest"], [EARNIE_GHCR_UA, $auth]);
	if ($blob !== null && in_array($blob["status"], [301, 302, 303, 307, 308], true)) {
		// Signed storage URL: must be fetched without the registry token.
		if (strpos($blob["location"], "https://") !== 0) {
			return $fail("config blob: unexpected redirect");
		}
		$blob = earnie_ghcr_get($blob["location"], [EARNIE_GHCR_UA]);
	}
	if ($blob === null) {
		return $fail("config blob: network error");
	}
	if ($blob["status"] !== 200) {
		return $fail("config blob: HTTP " . $blob["status"]);
	}
	$cfg = json_decode($blob["body"], true);
	$labels = isset($cfg["config"]["Labels"]) && is_array($cfg["config"]["Labels"])
		? $cfg["config"]["Labels"]
		: [];
	if (empty($labels[EARNIE_GHCR_VERSION_LABEL])) {
		return $fail(":$tag has no " . EARNIE_GHCR_VERSION_LABEL . " label (image built before the label existed)");
	}
	return ["version" => (string) $labels[EARNIE_GHCR_VERSION_LABEL], "error" => ""];
}
