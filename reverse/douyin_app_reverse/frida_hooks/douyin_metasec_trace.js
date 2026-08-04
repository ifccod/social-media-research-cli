"use strict";

// 研究探针，绑定抖音 Android 32.2.6；观测 MetaSec、安装身份和 frameSign，
// 仅用于采集证据，不登记为可调用 CLI 接口。
let showSensitive = false;

function render(value) {
  if (value === null || value === undefined) {
    return "<null>";
  }
  const text = String(value);
  if (showSensitive || text.length <= 8) {
    return text;
  }
  return `${text.slice(0, 4)}...${text.slice(-4)} (len=${text.length})`;
}

function renderMap(value) {
  if (value === null || value === undefined) {
    return "<null>";
  }
  try {
    const entries = [];
    const iterator = value.entrySet().iterator();
    while (iterator.hasNext()) {
      const entry = iterator.next();
      entries.push(`${entry.getKey()}=${render(entry.getValue())}`);
    }
    return `{${entries.join(", ")}}`;
  } catch (error) {
    return `<map-render-error: ${error}>`;
  }
}

rpc.exports = {
  setsensitive(enabled) {
    showSensitive = Boolean(enabled);
    return { showSensitive };
  },
};

Java.perform(() => {
  const ManagerUtils = Java.use(
    "com.bytedance.mobsec.metasec.ml.MSManagerUtils",
  );
  const Manager = Java.use("com.bytedance.mobsec.metasec.ml.MSManager");

  const init = ManagerUtils.init.overload(
    "android.content.Context",
    "X.5q0",
  );
  init.implementation = function (context, config) {
    const result = init.call(this, context, config);
    console.log(`[douyin-metasec] init result=${result}`);
    return result;
  };

  const get = ManagerUtils.get.overload("java.lang.String");
  get.implementation = function (appId) {
    const result = get.call(this, appId);
    console.log(
      `[douyin-metasec] get app_id=${render(appId)} manager=${result !== null}`,
    );
    return result;
  };

  const setDeviceID = Manager.setDeviceID.overload("java.lang.String");
  setDeviceID.implementation = function (value) {
    console.log(`[douyin-metasec] setDeviceID ${render(value)}`);
    return setDeviceID.call(this, value);
  };

  const setInstallID = Manager.setInstallID.overload("java.lang.String");
  setInstallID.implementation = function (value) {
    console.log(`[douyin-metasec] setInstallID ${render(value)}`);
    return setInstallID.call(this, value);
  };

  const setSessionID = Manager.setSessionID.overload("java.lang.String");
  setSessionID.implementation = function (value) {
    console.log(`[douyin-metasec] setSessionID ${render(value)}`);
    return setSessionID.call(this, value);
  };

  const frameSign = Manager.frameSign.overload("java.lang.String", "int");
  frameSign.implementation = function (stringToSign, scene) {
    const result = frameSign.call(this, stringToSign, scene);
    console.log(
      `[douyin-metasec] frameSign scene=${scene} input=${render(stringToSign)} output=${renderMap(result)}`,
    );
    return result;
  };

  console.log("[douyin-metasec] hooks installed");
});
