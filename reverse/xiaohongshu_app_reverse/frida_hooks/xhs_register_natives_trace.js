'use strict';

// 研究探针，绑定小红书 Android 9.39.1；记录 JNI 动态注册信息，
// 仅用于采集证据，不登记为可调用 CLI 接口。
function findRegisterNatives() {
  var libart = Process.getModuleByName('libart.so');
  var symbols = libart.enumerateSymbols();
  for (var i = 0; i < symbols.length; i += 1) {
    var symbol = symbols[i];
    if (symbol.name.indexOf('RegisterNatives') !== -1 &&
        symbol.name.indexOf('CheckJNI') === -1) {
      return symbol.address;
    }
  }
  throw new Error('libart RegisterNatives symbol was not found');
}

function safeCString(pointer) {
  try {
    return pointer.isNull() ? null : pointer.readCString();
  } catch (error) {
    return '<read-error:' + String(error) + '>';
  }
}

function className(classHandle) {
  try {
    var env = Java.vm.tryGetEnv();
    if (env === null) {
      return null;
    }
    return env.getClassName(classHandle);
  } catch (error) {
    return '<class-error:' + String(error) + '>';
  }
}

Java.perform(function () {
  var address = findRegisterNatives();
  Interceptor.attach(address, {
    onEnter: function (args) {
      var klass = className(args[1]);
      var methods = args[2];
      var count = args[3].toInt32();
      var entries = [];
      for (var i = 0; i < count; i += 1) {
        var entry = methods.add(i * Process.pointerSize * 3);
        var namePointer = entry.readPointer();
        var signaturePointer = entry.add(Process.pointerSize).readPointer();
        var functionPointer = entry.add(Process.pointerSize * 2).readPointer();
        var module = Process.findModuleByAddress(functionPointer);
        entries.push({
          name: safeCString(namePointer),
          signature: safeCString(signaturePointer),
          address: functionPointer.toString(),
          module: module === null ? null : module.name,
          module_offset: module === null
            ? null
            : functionPointer.sub(module.base).toString()
        });
      }
      if (klass === 'com.xingin.shield.http.Native' ||
          entries.some(function (entry) {
            return entry.module === 'libxyass.so';
          })) {
        send({
          source: 'xhs_register_natives_trace',
          event: 'register_natives',
          timestamp_ms: Date.now(),
          payload: {
            class_name: klass,
            count: count,
            methods: entries
          }
        });
      }
    }
  });

  send({
    source: 'xhs_register_natives_trace',
    event: 'hook.ready',
    timestamp_ms: Date.now(),
    payload: {
      register_natives: address.toString()
    }
  });
});
