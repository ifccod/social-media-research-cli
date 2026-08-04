'use strict';

// 研究探针，绑定小红书 Android 9.39.1；观测 shield 前后的 OkHttp 请求差分，
// 仅用于采集证据，不登记为可调用 CLI 接口。
var traceRawValues = false;
var maxBodyBytes = 1024 * 1024;

rpc.exports = {
  setraw: function (enabled) {
    traceRawValues = Boolean(enabled);
    return { raw_values: traceRawValues };
  },
  status: function () {
    return { raw_values: traceRawValues, max_body_bytes: maxBodyBytes };
  }
};

Java.perform(function () {
  var MessageDigest = Java.use('java.security.MessageDigest');
  var Buffer = Java.use('okio.Buffer');
  var Native = Java.use('com.xingin.shield.http.Native');

  function byteArrayHex(bytes) {
    var out = '';
    for (var i = 0; i < bytes.length; i += 1) {
      var value = bytes[i];
      if (value < 0) {
        value += 256;
      }
      out += ('0' + value.toString(16)).slice(-2);
    }
    return out;
  }

  function sha256Bytes(bytes) {
    var digest = MessageDigest.getInstance('SHA-256');
    return byteArrayHex(digest.digest(bytes));
  }

  function sha256Text(value) {
    var JString = Java.use('java.lang.String');
    var bytes = JString.$new(String(value)).getBytes('UTF-8');
    return sha256Bytes(bytes);
  }

  function sensitiveHeader(name) {
    var normalized = String(name).toLowerCase();
    return normalized === 'cookie' ||
      normalized === 'set-cookie' ||
      normalized === 'authorization' ||
      normalized === 'proxy-authorization' ||
      normalized === 'x-auth-token' ||
      normalized === 'x-access-token';
  }

  function sensitiveQuery(name) {
    return /(^|_)(cookie|token|ticket|session|authorization|password|passwd|secret)($|_)/i
      .test(String(name));
  }

  function visibleValue(name, value, isSensitive) {
    var text = String(value);
    if (traceRawValues || !isSensitive(name)) {
      return text;
    }
    return {
      redacted: true,
      length: text.length,
      sha256: sha256Text(text)
    };
  }

  function querySnapshot(httpUrl) {
    var result = [];
    var names = httpUrl.queryParameterNames().iterator();
    while (names.hasNext()) {
      var name = String(names.next());
      var values = httpUrl.queryParameterValues(name);
      var captured = [];
      for (var i = 0; i < values.size(); i += 1) {
        captured.push(visibleValue(name, values.get(i), sensitiveQuery));
      }
      result.push({ name: name, values: captured });
    }
    return result;
  }

  function headersSnapshot(headers) {
    var result = {};
    var names = headers.names().iterator();
    while (names.hasNext()) {
      var name = String(names.next());
      var values = headers.values(name);
      var captured = [];
      for (var i = 0; i < values.size(); i += 1) {
        captured.push(visibleValue(name, values.get(i), sensitiveHeader));
      }
      result[name.toLowerCase()] = captured;
    }
    return result;
  }

  function bodySnapshot(body) {
    if (body === null) {
      return null;
    }
    var result = {
      content_type: body.contentType() === null ? null : String(body.contentType()),
      content_length: Number(body.contentLength())
    };
    try {
      if (body.isOneShot && body.isOneShot()) {
        result.hash_skipped = 'one_shot';
        return result;
      }
      if (body.isDuplex && body.isDuplex()) {
        result.hash_skipped = 'duplex';
        return result;
      }
    } catch (ignored) {
      // 较旧的 OkHttp 版本没有暴露这些方法。
    }
    if (result.content_length < 0 || result.content_length > maxBodyBytes) {
      result.hash_skipped = 'unknown_or_large';
      return result;
    }
    try {
      var buffer = Buffer.$new();
      body.writeTo(buffer);
      var size = Number(buffer.size());
      if (size > maxBodyBytes) {
        result.hash_skipped = 'large_after_write';
        return result;
      }
      var bytes = buffer.readByteArray();
      result.observed_length = size;
      result.sha256 = sha256Bytes(bytes);
    } catch (error) {
      result.hash_error = String(error);
    }
    return result;
  }

  function requestSnapshot(request) {
    if (request === null) {
      return null;
    }
    var url = request.url();
    return {
      method: String(request.method()),
      scheme: String(url.scheme()),
      host: String(url.host()),
      port: Number(url.port()),
      encoded_path: String(url.encodedPath()),
      query: querySnapshot(url),
      headers: headersSnapshot(request.headers()),
      body: bodySnapshot(request.body())
    };
  }

  function stableJSON(value) {
    return JSON.stringify(value);
  }

  function headerDiff(before, after) {
    var diff = { added: {}, changed: {}, removed: {} };
    var beforeHeaders = before === null ? {} : before.headers;
    var afterHeaders = after === null ? {} : after.headers;
    Object.keys(afterHeaders).forEach(function (name) {
      if (!(name in beforeHeaders)) {
        diff.added[name] = afterHeaders[name];
      } else if (stableJSON(beforeHeaders[name]) !== stableJSON(afterHeaders[name])) {
        diff.changed[name] = {
          before: beforeHeaders[name],
          after: afterHeaders[name]
        };
      }
    });
    Object.keys(beforeHeaders).forEach(function (name) {
      if (!(name in afterHeaders)) {
        diff.removed[name] = beforeHeaders[name];
      }
    });
    return diff;
  }

  function emit(event, payload) {
    send({
      source: 'xhs_shield_trace',
      event: event,
      timestamp_ms: Date.now(),
      payload: payload
    });
  }

  var initializeNative = Native.initializeNative.overload();
  initializeNative.implementation = function () {
    emit('native.initializeNative.enter', {});
    var result = initializeNative.call(Native);
    emit('native.initializeNative.leave', {});
    return result;
  };

  var initialize = Native.initialize.overload('java.lang.String');
  initialize.implementation = function (token) {
    emit('native.initialize.enter', { token: String(token) });
    var pointer = initialize.call(Native, token);
    emit('native.initialize.leave', {
      token: String(token),
      c_ptr: String(pointer)
    });
    return pointer;
  };

  var destroy = Native.destroy.overload('long');
  destroy.implementation = function (pointer) {
    emit('native.destroy', { c_ptr: String(pointer) });
    return destroy.call(Native, pointer);
  };

  var intercept = Native.intercept.overload(
    'okhttp3.Interceptor$Chain',
    'long'
  );
  intercept.implementation = function (chain, pointer) {
    var before = requestSnapshot(chain.request());
    emit('native.intercept.enter', {
      c_ptr: String(pointer),
      request: before
    });
    try {
      var response = intercept.call(Native, chain, pointer);
      var after = response === null ? null : requestSnapshot(response.request());
      emit('native.intercept.leave', {
        c_ptr: String(pointer),
        status: response === null ? null : Number(response.code()),
        request: after,
        header_diff: headerDiff(before, after)
      });
      return response;
    } catch (error) {
      emit('native.intercept.error', {
        c_ptr: String(pointer),
        error: String(error)
      });
      throw error;
    }
  };

  [
    'okhttp3.internal.http.RealInterceptorChain',
    'okhttp3.RealInterceptorChain'
  ].forEach(function (className) {
    try {
      var RealInterceptorChain = Java.use(className);
      var proceed = RealInterceptorChain.proceed.overload('okhttp3.Request');
      proceed.implementation = function (request) {
        emit('okhttp.proceed', {
          implementation: className,
          request: requestSnapshot(request)
        });
        return proceed.call(this, request);
      };
      emit('hook.installed', { class_name: className, method: 'proceed' });
    } catch (ignored) {
      // 当前 APK 可能使用了其他 OkHttp 主版本。
    }
  });

  emit('hook.ready', {
    package: 'com.xingin.xhs',
    raw_values: traceRawValues,
    max_body_bytes: maxBodyBytes
  });
});
