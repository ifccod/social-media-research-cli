"use strict";

// 研究探针，绑定 TikTok Android 38.3.3；观测设备注册、MSSDK、DmtSec 和
// TicketGuard 生命周期，仅用于采集证据，不登记为可调用 CLI 接口。
var captureRawValues = false;
var schemaName = "reverse.tiktok.android.38.3.3.capture.v1";

function emitEvent(kind, data) {
  send({
    schema: schemaName,
    kind: kind,
    captured_at_ms: Date.now(),
    data: data,
  });
}

function asString(value) {
  if (value === null || value === undefined) {
    return "";
  }
  try {
    return String(value);
  } catch (_) {
    return "<unprintable>";
  }
}

function sha256(value) {
  var MessageDigest = Java.use("java.security.MessageDigest");
  var JString = Java.use("java.lang.String");
  var digest = MessageDigest.getInstance("SHA-256").digest(
    JString.$new(asString(value)).getBytes("UTF-8")
  );
  var output = "";
  for (var index = 0; index < digest.length; index += 1) {
    var byteValue = digest[index];
    if (byteValue < 0) {
      byteValue += 256;
    }
    output += ("0" + byteValue.toString(16)).slice(-2);
  }
  return output;
}

function protectedValue(name, value) {
  var stringValue = asString(value);
  if (captureRawValues) {
    return { name: name, value: stringValue };
  }
  return {
    name: name,
    sha256: sha256(stringValue),
    utf8_length: unescape(encodeURIComponent(stringValue)).length,
  };
}

function iteratorValues(iterator) {
  var values = [];
  while (iterator.hasNext()) {
    values.push(asString(iterator.next()));
  }
  return values;
}

function javaMapSnapshot(map) {
  var output = { keys: [], values: {} };
  if (map === null || map === undefined) {
    return output;
  }
  try {
    var iterator = map.entrySet().iterator();
    while (iterator.hasNext()) {
      var entry = iterator.next();
      var key = asString(entry.getKey());
      output.keys.push(key);
      output.values[key] = protectedValue(key, entry.getValue());
    }
    output.keys.sort();
  } catch (error) {
    output.error = asString(error);
  }
  return output;
}

function jsonKeys(jsonObject) {
  if (jsonObject === null || jsonObject === undefined) {
    return [];
  }
  try {
    return iteratorValues(jsonObject.keys()).sort();
  } catch (_) {
    return [];
  }
}

function jsonSnapshot(jsonObject) {
  var keys = jsonKeys(jsonObject);
  var output = { keys: keys, values: {} };
  keys.forEach(function (key) {
    try {
      output.values[key] = protectedValue(key, jsonObject.opt(key));
    } catch (error) {
      output.values[key] = { error: asString(error) };
    }
  });
  return output;
}

function urlSnapshot(url) {
  var value = asString(url);
  var output = {
    sha256: sha256(value),
    utf8_length: unescape(encodeURIComponent(value)).length,
    query_keys: [],
  };
  try {
    var Uri = Java.use("android.net.Uri");
    var parsed = Uri.parse(value);
    output.host = asString(parsed.getHost());
    output.path = asString(parsed.getPath());
    output.query_keys = iteratorValues(
      parsed.getQueryParameterNames().iterator()
    ).sort();
  } catch (error) {
    output.parse_error = asString(error);
  }
  if (captureRawValues) {
    output.value = value;
  }
  return output;
}

function headerListSnapshot(headers) {
  var output = { keys: [], values: {} };
  if (headers === null || headers === undefined) {
    return output;
  }
  try {
    var iterator = headers.iterator();
    while (iterator.hasNext()) {
      var header = iterator.next();
      var name = "";
      var value = "";
      try {
        name = asString(header.LIZ.value);
        value = asString(header.LIZIZ.value);
      } catch (_) {
        name = asString(header);
      }
      output.keys.push(name);
      output.values[name] = protectedValue(name, value);
    }
    output.keys.sort();
  } catch (error) {
    output.error = asString(error);
  }
  return output;
}

function resultHeaderSnapshot(result) {
  if (result === null || result === undefined) {
    return { keys: [], values: {} };
  }
  try {
    return headerListSnapshot(result.LIZIZ.value);
  } catch (error) {
    return { keys: [], values: {}, error: asString(error) };
  }
}

function hookSecurityFactor() {
  var SecurityFactor = Java.use("ms.bd.o.i2$a");
  var method = SecurityFactor.onCallToAddSecurityFactor.overload(
    "java.lang.String",
    "java.util.Map"
  );
  method.implementation = function (url, headers) {
    var result = method.call(this, url, headers);
    emitEvent("security_factor", {
      url: urlSnapshot(url),
      input_headers: javaMapSnapshot(headers),
      output_headers: javaMapSnapshot(result),
    });
    return result;
  };
}

function hookDeviceIdentity() {
  var DmtSec = Java.use("com.ss.android.ugc.aweme.sec.DmtSec");
  [
    "updateDeviceIdAndInstallId",
    "updateDeviceInfo",
  ].forEach(function (methodName) {
    try {
      var method = DmtSec[methodName].overload(
        "java.lang.String",
        "java.lang.String"
      );
      method.implementation = function (deviceId, installId) {
        emitEvent("device_identity_update", {
          method: methodName,
          device_id: protectedValue("device_id", deviceId),
          install_id: protectedValue("install_id", installId),
        });
        return method.call(this, deviceId, installId);
      };
    } catch (error) {
      emitEvent("hook_error", {
        hook: "DmtSec." + methodName,
        error: asString(error),
      });
    }
  });

  try {
    var frameSign = DmtSec.frameSign.overload("java.lang.String", "int");
    frameSign.implementation = function (value, scene) {
      var result = frameSign.call(this, value, scene);
      emitEvent("frame_sign", {
        scene: scene,
        input: protectedValue("input", value),
        output: javaMapSnapshot(result),
      });
      return result;
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "DmtSec.frameSign",
      error: asString(error),
    });
  }
}

function hookDeviceRegistration() {
  var RegisterController = Java.use("X.aVY");
  try {
    var request = RegisterController.LJ.overload(
      "java.lang.String",
      "org.json.JSONObject"
    );
    request.implementation = function (payload, header) {
      var payloadObject = null;
      try {
        payloadObject = Java.use("org.json.JSONObject").$new(payload);
      } catch (_) {
        payloadObject = null;
      }
      emitEvent("device_register_request", {
        payload: captureRawValues
          ? { value: asString(payload) }
          : protectedValue("payload", payload),
        payload_keys: jsonKeys(payloadObject),
        header: jsonSnapshot(header),
      });
      return request.call(this, payload, header);
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "X.aVY.LJ",
      error: asString(error),
    });
  }

  try {
    var response = RegisterController.LJI.overload("org.json.JSONObject");
    response.implementation = function (payload) {
      emitEvent("device_register_response", jsonSnapshot(payload));
      return response.call(this, payload);
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "X.aVY.LJI",
      error: asString(error),
    });
  }
}

function hookTicketGuard() {
  var TicketGuard = Java.use("X.XKj");
  try {
    var provider = TicketGuard.getProviderContent.overload(
      "com.bytedance.android.sdk.ticketguard.ProviderRequestParam"
    );
    provider.implementation = function (param) {
      var result = provider.call(this, param);
      emitEvent("ticket_guard_provider_request", {
        result_headers: resultHeaderSnapshot(result),
      });
      return result;
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "TicketGuard.getProviderContent",
      error: asString(error),
    });
  }

  try {
    var consumer = TicketGuard.getConsumerRequestContent.overload("X.XEe");
    consumer.implementation = function (param) {
      var result = consumer.call(this, param);
      emitEvent("ticket_guard_consumer_request", {
        result_headers: resultHeaderSnapshot(result),
      });
      return result;
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "TicketGuard.getConsumerRequestContent",
      error: asString(error),
    });
  }

  try {
    var providerResponse = TicketGuard.handleProviderResponse.overload("X.XKe");
    providerResponse.implementation = function (param) {
      var result = providerResponse.call(this, param);
      emitEvent("ticket_guard_provider_response", {
        result_headers: headerListSnapshot(result),
      });
      return result;
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "TicketGuard.handleProviderResponse",
      error: asString(error),
    });
  }

  try {
    var consumerResponse = TicketGuard.handleConsumerResponse.overload(
      "com.bytedance.android.sdk.ticketguard.HandleConsumerResponseParam"
    );
    consumerResponse.implementation = function (param) {
      emitEvent("ticket_guard_consumer_response", {});
      return consumerResponse.call(this, param);
    };
  } catch (error) {
    emitEvent("hook_error", {
      hook: "TicketGuard.handleConsumerResponse",
      error: asString(error),
    });
  }
}

rpc.exports = {
  configure: function (options) {
    options = options || {};
    captureRawValues = options.raw === true;
    return {
      schema: schemaName,
      raw: captureRawValues,
    };
  },
};

Java.perform(function () {
  [
    hookSecurityFactor,
    hookDeviceIdentity,
    hookDeviceRegistration,
    hookTicketGuard,
  ].forEach(function (install) {
    try {
      install();
    } catch (error) {
      emitEvent("hook_error", {
        hook: install.name,
        error: asString(error),
      });
    }
  });
  emitEvent("ready", {
    package: "com.zhiliaoapp.musically",
    app_version: "38.3.3",
    app_build: "2023803030",
    raw: captureRawValues,
  });
});
