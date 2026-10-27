package com.resolveflow.evaluation;

import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.MeterRegistry;
import java.lang.reflect.*;
import java.net.InetSocketAddress;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import javax.sql.DataSource;
import org.aopalliance.intercept.MethodInterceptor;
import org.springframework.aop.framework.Advised;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.ObjectMapper;

/** Measurement bootstrap around byte-identical extracted application classes. Never packaged in production. */
public final class D5Probe {
    static final ObjectMapper JSON=new ObjectMapper();
    static final AtomicLong statements=new AtomicLong(),failures=new AtomicLong(),returnedRows=new AtomicLong();
    static final AtomicInteger inflight=new AtomicInteger(),peak=new AtomicInteger();
    static final AtomicReference<Gate> gate=new AtomicReference<>();
    static final List<String> sqlSamples=new CopyOnWriteArrayList<>();
    static volatile ConfigurableApplicationContext context;
    static volatile boolean events;
    static Path folder;
    static String identity,node;
    record Gate(String id,String product,String mode,CountDownLatch release,AtomicBoolean entered) {}
    static synchronized void event(Map<String,Object> record) {
        if(!events)return;
        var row=new LinkedHashMap<>(record);row.put("node",node);row.put("pid",ProcessHandle.current().pid());row.put("at",Instant.now().toString());row.put("nano",System.nanoTime());
        try {Files.writeString(folder.resolve(node+"-events.jsonl"),JSON.writeValueAsString(row)+"\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);}
        catch(Exception error){throw new IllegalStateException("cannot persist probe event",error);}
    }
    static Object invoke(Object target,Method method,Object[] args)throws Throwable {
        try{return method.invoke(target,args);}catch(InvocationTargetException error){throw error.getCause();}
    }
    static class CountedSource extends DelegatingDataSource implements AutoCloseable {
        CountedSource(DataSource target){super(target);}
        @Override public void close()throws Exception {if(getTargetDataSource() instanceof AutoCloseable target)target.close();}
        @Override public Connection getConnection()throws SQLException{return counted(super.getConnection());}
        @Override public Connection getConnection(String u,String p)throws SQLException{return counted(super.getConnection(u,p));}
        static Connection counted(Connection connection) {
            return (Connection)Proxy.newProxyInstance(Connection.class.getClassLoader(),new Class<?>[]{Connection.class},(p,m,a)->{
                Object value=invoke(connection,m,a);
                if(value instanceof Statement statement && (m.getName().equals("prepareStatement")||m.getName().equals("createStatement"))) {
                    String sql=m.getName().equals("prepareStatement")?(String)a[0]:"<dynamic statement>";
                    Class<?> contract=value instanceof PreparedStatement?PreparedStatement.class:Statement.class;
                    return Proxy.newProxyInstance(contract.getClassLoader(),new Class<?>[]{contract},(p2,m2,a2)-> {
                        boolean execute=m2.getName().startsWith("execute");
                        if(!execute)return invoke(statement,m2,a2);
                        statements.incrementAndGet();int active=inflight.incrementAndGet();peak.accumulateAndGet(active,Math::max);
                        if(sqlSamples.size()<12&&!sqlSamples.contains(sql))sqlSamples.add(sql);
                        try {
                            Object result=invoke(statement,m2,a2);
                            if(result instanceof ResultSet rs)return Proxy.newProxyInstance(ResultSet.class.getClassLoader(),new Class<?>[]{ResultSet.class},(p3,m3,a3)->{
                                Object next=invoke(rs,m3,a3);if(m3.getName().equals("next")&&Boolean.TRUE.equals(next))returnedRows.incrementAndGet();return next;
                            });
                            return result;
                        }catch(Throwable error){failures.incrementAndGet();throw error;}
                        finally{inflight.decrementAndGet();}
                    });
                }
                return value;
            });
        }
    }
    static void attachReviewProbe()throws Exception {
        Object reviews;
        try{reviews=context.getBean(Class.forName("com.resolveflow.commerce.catalog.ProductReviewService"));}
        catch(ClassNotFoundException notCommerce){return;}
        ((Advised)reviews).addAdvice(0,(MethodInterceptor)call->{
            if(!call.getMethod().getName().equals("publicPage"))return call.proceed();
            String product=(String)call.getArguments()[0],id=UUID.randomUUID().toString();
            event(Map.of("stage","load_start","product",product,"call",id));
            try {
                Object value=call.proceed();
                Gate control=gate.get();
                if(control!=null&&control.product().equals(product)) {
                    if(TransactionSynchronizationManager.isActualTransactionActive())throw new AssertionError("fault gate inside business transaction");
                    event(Map.of("stage","snapshot_ready","product",product,"call",id,"gate_id",control.id()));
                    if(control.entered().compareAndSet(false,true))Files.writeString(folder.resolve(node+"-"+control.id()+".entered"),id,StandardOpenOption.CREATE_NEW);
                    if(!control.release().await(15,TimeUnit.SECONDS))throw new AssertionError("lab gate expired");
                    if(control.mode().equals("fail"))throw new IllegalStateException("explicit D5 post-query test fault");
                }
                return value;
            }finally{event(Map.of("stage","load_end","product",product,"call",id));}
        });
    }
    static Map<String,Object> snapshot() {
        var meters=new TreeMap<String,Double>();
        for(var meter:context.getBean(MeterRegistry.class).getMeters()) {
            if(meter.getId().getName().startsWith("resolveflow."))for(var value:meter.measure())meters.put(meter.getId().getName()+meter.getId().getTags()+":"+value.getStatistic(),value.getValue());
        }
        return Map.of("pid",ProcessHandle.current().pid(),"node",node,"sql",statements.get(),"failed_sql",failures.get(),"sql_inflight",inflight.get(),"sql_peak",peak.get(),"rows_returned",returnedRows.get(),"meters",meters,"sampled_sql",sqlSamples);
    }
    public static void main(String[] args)throws Exception {
        identity=System.getProperty("rf.d5.run");node=System.getProperty("rf.d5.node");folder=Path.of(System.getProperty("rf.d5.folder")).toAbsolutePath();
        if(identity==null||!identity.matches("[a-f0-9]{32}")||node==null||!node.matches("[a-z0-9_-]{1,40}")||!Files.isDirectory(folder))throw new IllegalArgumentException("explicit owned D5 bootstrap arguments required");
        var app=new SpringApplication(Class.forName(args[0]));
        app.addInitializers(ctx->ctx.getBeanFactory().addBeanPostProcessor(new BeanPostProcessor(){
            @Override public Object postProcessAfterInitialization(Object bean,String name){return bean instanceof DataSource ds?new CountedSource(ds):bean;}
        }));
        context=app.run(Arrays.copyOfRange(args,1,args.length));attachReviewProbe();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",Integer.getInteger("rf.d5.probe-port")),0);
        var controls=Executors.newFixedThreadPool(2);server.setExecutor(controls);
        server.createContext("/",exchange->{
            if(!identity.equals(exchange.getRequestHeaders().getFirst("X-D5-Run"))){exchange.sendResponseHeaders(403,-1);exchange.close();return;}
            try {
                String path=exchange.getRequestURI().getPath();
                if(!path.equals("/snapshot")&&!exchange.getRequestMethod().equals("POST"))throw new IllegalArgumentException("POST control required");
                switch(path){
                    case "/begin" -> {if(inflight.get()!=0)throw new IllegalStateException("SQL still active");peak.set(0);sqlSamples.clear();}
                    case "/events/on" -> events=true;
                    case "/events/off" -> events=false;
                    case "/release" -> {Gate old=gate.getAndSet(null);if(old!=null)old.release().countDown();}
                    case "/gate" -> {var v=JSON.readTree(exchange.getRequestBody());String id=v.path("id").asString(),product=v.path("product").asString(),mode=v.path("mode").asString();if(!id.matches("[A-Za-z0-9_-]{1,64}")||!product.matches("[A-Za-z0-9_-]{1,64}")||!List.of("hold","fail").contains(mode)||gate.get()!=null)throw new IllegalArgumentException("invalid or overlapping fault gate");gate.set(new Gate(id,product,mode,new CountDownLatch(1),new AtomicBoolean()));}
                    case "/snapshot" -> {}
                    default -> throw new IllegalArgumentException("unknown control");
                }
                byte[] body=JSON.writeValueAsBytes(snapshot());exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);
            }catch(Exception error){byte[] body=JSON.writeValueAsBytes(Map.of("error",error.getClass().getSimpleName()));exchange.sendResponseHeaders(400,body.length);exchange.getResponseBody().write(body);}
            finally{exchange.close();}
        });server.start();
        Runtime.getRuntime().addShutdownHook(new Thread(()->{server.stop(0);controls.shutdownNow();context.close();}));
        Files.writeString(folder.resolve(node+".ready"),JSON.writeValueAsString(snapshot()),StandardOpenOption.CREATE_NEW);
    }
}
